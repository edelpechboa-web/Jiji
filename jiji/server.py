"""Serveur HTTP (bibliothèque standard) : API JSON + interface web statique."""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from . import api
from .api import ApiError
from .db import connect, get_settings, init_db

SESSION_TTL = 12 * 3600
COOKIE = "jiji_session"
MAX_BODY = 5 * 1024 * 1024
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


class Raw:
    """Réponse non JSON (CSV, sauvegarde…)."""

    def __init__(self, body, content_type, filename=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.content_type = content_type
        self.filename = filename


class Request:
    def __init__(self, conn, method, query, body, user, params):
        self.conn, self.method, self.query, self.body, self.user, self.params = conn, method, query, body, user, params

    def int(self, name):
        return int(self.params[name])


ROUTES = []


def route(method, pattern, public=False):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, public))
        return fn
    return deco


# ----- authentification ------------------------------------------------------
_failures = {}
_failures_lock = threading.Lock()


def _check_rate_limit(ip):
    with _failures_lock:
        count, until = _failures.get(ip, (0, 0))
        if until > time.time():
            raise ApiError("Trop de tentatives. Réessayez dans une minute.", 429)


def _record_failure(ip):
    with _failures_lock:
        count, _ = _failures.get(ip, (0, 0))
        count += 1
        _failures[ip] = (count, time.time() + 60 if count >= 5 else 0)


def _open_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE created < ?", (time.time() - SESSION_TTL,))
    conn.execute("INSERT INTO sessions(token, user_id, created) VALUES (?, ?, ?)", (token, user_id, time.time()))
    conn.commit()
    return token


@route("GET", "/api/status", public=True)
def status(req):
    has_users = bool(req.conn.execute("SELECT 1 FROM users").fetchone())
    settings = get_settings(req.conn)
    return {"setup_needed": not has_users, "authenticated": req.user is not None,
            "user": req.user["username"] if req.user else None, "school_name": settings["school_name"]}


@route("POST", "/api/setup", public=True)
def setup(req):
    if req.conn.execute("SELECT 1 FROM users").fetchone():
        raise ApiError("L'application est déjà configurée.", 403)
    username = str(req.body.get("username", "")).strip()
    password = str(req.body.get("password", ""))
    if not username or len(password) < 6:
        raise ApiError("Identifiant requis et mot de passe d'au moins 6 caractères.")
    salt, digest = hash_password(password)
    cur = req.conn.execute("INSERT INTO users(username, salt, pw_hash) VALUES (?, ?, ?)", (username, salt, digest))
    school = str(req.body.get("school_name", "")).strip()
    if school:
        api.update_settings(req.conn, {"school_name": school})
    return Raw(json.dumps({"ok": True}), "application/json", None), _open_session(req.conn, cur.lastrowid)


@route("POST", "/api/login", public=True)
def login(req):
    ip = req.params.get("_ip", "")
    _check_rate_limit(ip)
    row = req.conn.execute("SELECT * FROM users WHERE username = ?", (str(req.body.get("username", "")).strip(),)).fetchone()
    password = str(req.body.get("password", ""))
    ok = False
    if row:
        _, digest = hash_password(password, row["salt"])
        ok = hmac.compare_digest(digest, row["pw_hash"])
    else:
        hash_password(password)  # temps constant approximatif
    if not ok:
        _record_failure(ip)
        raise ApiError("Identifiant ou mot de passe incorrect.", 401)
    with _failures_lock:
        _failures.pop(ip, None)
    return Raw(json.dumps({"ok": True}), "application/json", None), _open_session(req.conn, row["id"])


@route("POST", "/api/logout", public=True)
def logout(req):
    token = req.params.get("_token")
    if token:
        req.conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        req.conn.commit()
    return {"ok": True}


@route("POST", "/api/password")
def change_password(req):
    old, new = str(req.body.get("old", "")), str(req.body.get("new", ""))
    row = req.conn.execute("SELECT * FROM users WHERE id = ?", (req.user["id"],)).fetchone()
    if not hmac.compare_digest(hash_password(old, row["salt"])[1], row["pw_hash"]):
        raise ApiError("Ancien mot de passe incorrect.", 403)
    if len(new) < 6:
        raise ApiError("Le nouveau mot de passe doit contenir au moins 6 caractères.")
    salt, digest = hash_password(new)
    req.conn.execute("UPDATE users SET salt = ?, pw_hash = ? WHERE id = ?", (salt, digest, row["id"]))
    req.conn.execute("DELETE FROM sessions WHERE user_id = ? AND token != ?", (row["id"], req.params["_token"]))
    req.conn.commit()
    return {"ok": True}


# ----- paramètres, tableau de bord ------------------------------------------
@route("GET", "/api/settings")
def get_settings_route(req):
    return get_settings(req.conn)


@route("PUT", "/api/settings")
def put_settings(req):
    return api.update_settings(req.conn, req.body)


@route("GET", "/api/dashboard")
def dashboard(req):
    year = req.query.get("year_id")
    return api.dashboard(req.conn, int(year) if year and year.isdigit() else None)


@route("GET", "/api/backup")
def backup(req):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Raw(req.conn.serialize(), "application/octet-stream", f"jiji-sauvegarde-{stamp}.db")


# ----- CRUD générique -------------------------------------------------------
@route("GET", r"/api/(?P<res>[a-z-]+)")
def crud_list(req):
    _need_resource(req)
    return api.list_rows(req.conn, req.params["res"], req.query)


@route("POST", r"/api/(?P<res>[a-z-]+)")
def crud_create(req):
    _need_resource(req)
    return api.create_row(req.conn, req.params["res"], req.body)


@route("GET", r"/api/(?P<res>[a-z-]+)/(?P<id>\d+)")
def crud_get(req):
    _need_resource(req)
    rows = api.list_rows(req.conn, req.params["res"], {}, req.int("id"))
    if not rows:
        raise ApiError("Élément introuvable.", 404)
    return rows[0]


@route("PUT", r"/api/(?P<res>[a-z-]+)/(?P<id>\d+)")
def crud_update(req):
    _need_resource(req)
    return api.update_row(req.conn, req.params["res"], req.int("id"), req.body)


@route("DELETE", r"/api/(?P<res>[a-z-]+)/(?P<id>\d+)")
def crud_delete(req):
    _need_resource(req)
    api.delete_row(req.conn, req.params["res"], req.int("id"))
    return {"ok": True}


def _need_resource(req):
    if req.params["res"] not in api.RESOURCES:
        raise ApiError("Ressource inconnue.", 404)


# ----- actions spécifiques --------------------------------------------------
@route("POST", r"/api/years/(?P<id>\d+)/periods/preset")
def periods_preset(req):
    api.create_period_preset(req.conn, req.int("id"), req.body.get("kind"))
    return api.list_rows(req.conn, "periods", {"year_id": str(req.int("id"))})


@route("POST", r"/api/classes/(?P<id>\d+)/subjects/copy")
def copy_subjects(req):
    api.copy_class_subjects(req.conn, req.int("id"), int(req.body.get("from_class_id") or 0))
    return api.list_rows(req.conn, "class-subjects", {"class_id": str(req.int("id"))})


@route("POST", r"/api/classes/(?P<id>\d+)/students/import")
def import_students(req):
    return api.import_students(req.conn, req.int("id"), req.body.get("csv", ""))


@route("GET", r"/api/evaluations/(?P<id>\d+)/grades")
def grades_get(req):
    return api.get_grades(req.conn, req.int("id"))


@route("PUT", r"/api/evaluations/(?P<id>\d+)/grades")
def grades_put(req):
    return api.save_grades(req.conn, req.int("id"), req.body)


@route("GET", r"/api/classes/(?P<id>\d+)/report")
def class_report(req):
    return api.report(req.conn, req.int("id"), req.query.get("period"))


@route("GET", r"/api/classes/(?P<id>\d+)/report\.csv")
def class_report_csv(req):
    text = api.report_csv(req.conn, req.int("id"), req.query.get("period"))
    return Raw(text, "text/csv; charset=utf-8", f'resultats-classe-{req.int("id")}.csv')


def _hostname(header):
    if header.startswith("["):
        return header.split("]")[0] + "]"
    return header.rsplit(":", 1)[0] if ":" in header else header


# ----- gestionnaire HTTP ----------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "Jiji/1.0"
    db_path = "jiji.db"
    loopback_only = True

    def log_message(self, fmt, *args):
        if os.environ.get("JIJI_DEBUG"):
            super().log_message(fmt, *args)

    # -- helpers
    def _send(self, status, body, content_type, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj, extra=None):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", extra)

    def _token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[COOKIE].value if COOKIE in cookie else None

    def _cookie_header(self, token, expire=False):
        attrs = f"{COOKIE}={'' if expire else token}; Path=/; HttpOnly; SameSite=Strict"
        return ("Set-Cookie", attrs + ("; Max-Age=0" if expire else f"; Max-Age={SESSION_TTL}"))

    # -- dispatch
    def _handle(self, method):
        url = urlparse(self.path)
        if self.loopback_only:
            host = _hostname(self.headers.get("Host") or "")
            if host not in LOCAL_HOSTS:
                return self._json(403, {"error": "Hôte non autorisé."})
        if not url.path.startswith("/api/"):
            return self._static(url.path) if method == "GET" else self._json(405, {"error": "Méthode non autorisée."})
        if method != "GET" and self.headers.get("X-Requested-With") != "jiji":
            return self._json(403, {"error": "En-tête de sécurité manquant."})
        body = {}
        if method in ("POST", "PUT"):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "Requête trop volumineuse."})
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "JSON invalide."})
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        conn = connect(self.db_path)
        try:
            token = self._token()
            user = None
            if token:
                user = conn.execute(
                    "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.created > ?",
                    (token, time.time() - SESSION_TTL),
                ).fetchone()
            for m, pattern, fn, public in ROUTES:
                match = pattern.match(url.path)
                if m == method and match:
                    break
            else:
                return self._json(404, {"error": "Route inconnue."})
            if not public and user is None:
                return self._json(401, {"error": "Authentification requise."})
            params = {**match.groupdict(), "_ip": self.client_address[0], "_token": token}
            req = Request(conn, method, query, body, user, params)
            result = fn(req)
            extra = []
            if isinstance(result, tuple):  # (réponse, nouveau jeton de session)
                result, new_token = result
                extra.append(self._cookie_header(new_token))
            if fn is logout:
                extra.append(self._cookie_header("", expire=True))
            if isinstance(result, Raw):
                if result.filename:
                    extra.append(("Content-Disposition", f'attachment; filename="{result.filename}"'))
                return self._send(200, result.body, result.content_type, extra)
            return self._json(200, result, extra)
        except ApiError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except sqlite3.Error as exc:
            conn.rollback()
            return self._json(500, {"error": "Erreur de base de données.", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": "Erreur interne.", "detail": str(exc)})
        finally:
            conn.close()

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        parts = rel.split("/")
        if any(p in ("", ".", "..") or "\\" in p for p in parts):
            return self._json(404, {"error": "Page introuvable."})
        target = resources.files("jiji").joinpath("static", *parts)
        if not target.is_file():
            return self._json(404, {"error": "Page introuvable."})
        ctype = mimetypes.guess_type(parts[-1])[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self): self._handle("GET")
    def do_POST(self): self._handle("POST")
    def do_PUT(self): self._handle("PUT")
    def do_DELETE(self): self._handle("DELETE")


def make_server(db_path, host="127.0.0.1", port=8765):
    conn = connect(db_path)
    init_db(conn)
    conn.close()
    handler = type("BoundHandler", (Handler,), {"db_path": db_path, "loopback_only": host in ("127.0.0.1", "localhost", "::1")})
    return ThreadingHTTPServer((host, port), handler)
