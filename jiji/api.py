"""Logique métier de l'API : CRUD générique, import CSV, notes, rapports."""
import csv
import io
import re
import sqlite3
from datetime import datetime

from . import calc
from .db import get_settings


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
LABELS = {
    "name": "Le nom", "year_id": "L'année", "weight": "Le poids", "position": "La position",
    "code": "Le code", "track_id": "La filière", "class_id": "La classe", "subject_id": "La matière",
    "coef": "Le coefficient", "teacher": "L'enseignant", "matricule": "Le matricule",
    "last_name": "Le nom de famille", "first_name": "Le prénom", "sex": "Le sexe",
    "birth_date": "La date de naissance", "class_subject_id": "La matière de classe",
    "period_id": "La période", "title": "L'intitulé", "kind": "Le type", "date": "La date",
    "max_score": "Le barème", "active": "L'état",
}


def coerce(field, kind, value):
    label = LABELS.get(field, field)
    if kind == "str":
        value = "" if value is None else str(value).strip()
        if len(value) > 200:
            raise ApiError(f"{label} est trop long.")
        return value
    if kind == "bool":
        return 1 if value in (True, 1, "1", "true") else 0
    if kind in ("int", "fk", "fk?"):
        if value in (None, "") and kind == "fk?":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError(f"{label} est invalide.")
    if kind == "num":
        try:
            if isinstance(value, str):
                value = value.replace(",", ".")
            number = float(value)
        except (TypeError, ValueError):
            raise ApiError(f"{label} doit être un nombre.")
        if number != number or number in (float("inf"), float("-inf")):
            raise ApiError(f"{label} doit être un nombre.")
        return number
    if kind == "date":
        value = "" if value is None else str(value).strip()
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise ApiError(f"{label} doit être au format AAAA-MM-JJ.")
        return value
    if kind == "sex":
        value = str(value or "").strip().upper()[:1]
        if value not in ("", "M", "F"):
            raise ApiError("Le sexe doit être M ou F.")
        return value
    raise ApiError(f"Type inconnu : {kind}", 500)


# (table, champs {nom: (type, obligatoire, défaut)}, SQL de base, filtres, tri)
RESOURCES = {
    "years": dict(
        table="years",
        fields={"name": ("str", True, None), "active": ("bool", False, 0)},
        select="SELECT y.* FROM years y", alias="y", filters={}, order="y.name DESC",
    ),
    "periods": dict(
        table="periods",
        fields={"year_id": ("fk", True, None), "name": ("str", True, None),
                "weight": ("num", False, 1), "position": ("int", False, 1)},
        select="SELECT p.* FROM periods p", alias="p", filters={"year_id": "p.year_id"},
        order="p.position, p.id",
    ),
    "tracks": dict(
        table="tracks",
        fields={"name": ("str", True, None), "code": ("str", False, "")},
        select="""SELECT t.*, (SELECT COUNT(*) FROM classes c WHERE c.track_id = t.id) AS class_count
                  FROM tracks t""",
        alias="t", filters={}, order="t.name COLLATE NOCASE",
    ),
    "subjects": dict(
        table="subjects",
        fields={"name": ("str", True, None), "code": ("str", False, "")},
        select="""SELECT s.*, (SELECT COUNT(*) FROM class_subjects cs WHERE cs.subject_id = s.id) AS class_count
                  FROM subjects s""",
        alias="s", filters={}, order="s.name COLLATE NOCASE",
    ),
    "classes": dict(
        table="classes",
        fields={"year_id": ("fk", True, None), "track_id": ("fk?", False, None), "name": ("str", True, None)},
        select="""SELECT c.*, t.name AS track_name,
                  (SELECT COUNT(*) FROM students s WHERE s.class_id = c.id) AS student_count,
                  (SELECT COUNT(*) FROM class_subjects cs WHERE cs.class_id = c.id) AS subject_count
                  FROM classes c LEFT JOIN tracks t ON t.id = c.track_id""",
        alias="c", filters={"year_id": "c.year_id", "track_id": "c.track_id"},
        order="c.name COLLATE NOCASE",
    ),
    "class-subjects": dict(
        table="class_subjects",
        fields={"class_id": ("fk", True, None), "subject_id": ("fk", True, None),
                "coef": ("num", False, 1), "teacher": ("str", False, "")},
        select="""SELECT cs.*, s.name AS subject_name FROM class_subjects cs
                  JOIN subjects s ON s.id = cs.subject_id""",
        alias="cs", filters={"class_id": "cs.class_id"}, order="s.name COLLATE NOCASE",
    ),
    "students": dict(
        table="students",
        fields={"matricule": ("str", False, ""), "last_name": ("str", True, None),
                "first_name": ("str", True, None), "sex": ("sex", False, ""),
                "birth_date": ("date", False, ""), "class_id": ("fk", True, None)},
        select="""SELECT st.*, c.name AS class_name FROM students st
                  JOIN classes c ON c.id = st.class_id""",
        alias="st", filters={"class_id": "st.class_id", "year_id": "c.year_id"},
        order="st.last_name COLLATE NOCASE, st.first_name COLLATE NOCASE",
    ),
    "evaluations": dict(
        table="evaluations",
        fields={"class_subject_id": ("fk", True, None), "period_id": ("fk", True, None),
                "title": ("str", True, None), "kind": ("str", False, "Devoir"),
                "date": ("date", False, ""), "max_score": ("num", False, 20), "weight": ("num", False, 1)},
        select="""SELECT e.*, s.name AS subject_name, cs.class_id, c.name AS class_name, p.name AS period_name,
                  (SELECT COUNT(*) FROM grades g WHERE g.evaluation_id = e.id
                     AND (g.score IS NOT NULL OR g.absent = 1)) AS graded_count,
                  (SELECT COUNT(*) FROM students st WHERE st.class_id = cs.class_id) AS student_count
                  FROM evaluations e
                  JOIN class_subjects cs ON cs.id = e.class_subject_id
                  JOIN subjects s ON s.id = cs.subject_id
                  JOIN classes c ON c.id = cs.class_id
                  JOIN periods p ON p.id = e.period_id""",
        alias="e",
        filters={"class_subject_id": "e.class_subject_id", "period_id": "e.period_id", "class_id": "cs.class_id"},
        order="e.date, e.id",
    ),
}

FRIENDLY_CONSTRAINTS = {
    "years.name": "Cette année existe déjà.",
    "periods.year_id, periods.name": "Cette période existe déjà dans cette année.",
    "tracks.name": "Cette filière existe déjà.",
    "subjects.name": "Cette matière existe déjà.",
    "classes.year_id, classes.name": "Une classe portant ce nom existe déjà cette année.",
    "class_subjects.class_id, class_subjects.subject_id": "Cette matière est déjà affectée à la classe.",
    "students.matricule": "Ce matricule est déjà utilisé.",
}


def friendly_integrity(exc):
    msg = str(exc)
    if msg.startswith("UNIQUE constraint failed: "):
        key = msg[len("UNIQUE constraint failed: "):]
        return FRIENDLY_CONSTRAINTS.get(key, "Cet enregistrement existe déjà.")
    if msg.startswith("CHECK"):
        return "Une valeur est hors limites (les nombres doivent être positifs)."
    if msg.startswith("FOREIGN KEY"):
        return "Référence invalide (élément lié introuvable)."
    return "Données invalides."


def list_rows(conn, name, query, row_id=None):
    spec = RESOURCES[name]
    where, args = [], []
    if row_id is not None:
        where.append(f'{spec["alias"]}.id = ?')
        args.append(row_id)
    for key, column in spec["filters"].items():
        if query.get(key) not in (None, ""):
            where.append(f"{column} = ?")
            args.append(int(query[key]) if query[key].lstrip("-").isdigit() else -1)
    if name == "students" and query.get("q"):
        where.append("(st.last_name LIKE ? OR st.first_name LIKE ? OR st.matricule LIKE ?)")
        args += [f'%{query["q"]}%'] * 3
    sql = spec["select"] + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + spec["order"]
    return [dict(r) for r in conn.execute(sql, args)]


def _cross_checks(conn, name, data, existing=None):
    merged = {**(existing or {}), **data}
    if name == "evaluations":
        row = conn.execute(
            """SELECT c.year_id AS cy, p.year_id AS py FROM class_subjects cs
               JOIN classes c ON c.id = cs.class_id, periods p
               WHERE cs.id = ? AND p.id = ?""",
            (merged["class_subject_id"], merged["period_id"]),
        ).fetchone()
        if row is None:
            raise ApiError("Matière ou période introuvable.")
        if row["cy"] != row["py"]:
            raise ApiError("La période n'appartient pas à l'année de la classe.")
        if existing and "max_score" in data:
            over = conn.execute(
                "SELECT COUNT(*) FROM grades WHERE evaluation_id = ? AND score > ?", (existing["id"], data["max_score"])
            ).fetchone()[0]
            if over:
                raise ApiError(f"{over} note(s) dépassent le nouveau barème.")
    if name == "class-subjects" and merged["coef"] <= 0:
        raise ApiError("Le coefficient doit être supérieur à 0.")
    if name == "classes" and existing and "year_id" in data and data["year_id"] != existing["year_id"]:
        raise ApiError("Une classe ne peut pas changer d'année scolaire.")


def _next_matricule(conn):
    n = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM students").fetchone()[0]
    while True:
        candidate = f"M{n:05d}"
        if not conn.execute("SELECT 1 FROM students WHERE matricule = ?", (candidate,)).fetchone():
            return candidate
        n += 1


def _set_active_year(conn, year_id):
    conn.execute("UPDATE years SET active = CASE WHEN id = ? THEN 1 ELSE 0 END", (year_id,))


def create_row(conn, name, body):
    spec = RESOURCES[name]
    data = {}
    for field, (kind, required, default) in spec["fields"].items():
        value = body.get(field)
        if value is not None and value != "":
            data[field] = coerce(field, kind, value)
        elif required:
            raise ApiError(f'{LABELS.get(field, field)} est obligatoire.')
        else:
            data[field] = default
        if required and kind == "str" and not data[field]:
            raise ApiError(f'{LABELS.get(field, field)} est obligatoire.')
    if name == "students" and not data["matricule"]:
        data["matricule"] = _next_matricule(conn)
    _cross_checks(conn, name, data)
    cols = ", ".join(data)
    try:
        cur = conn.execute(
            f'INSERT INTO {spec["table"]} ({cols}) VALUES ({", ".join("?" * len(data))})', list(data.values())
        )
        if name == "years":
            if data["active"] or conn.execute("SELECT COUNT(*) FROM years").fetchone()[0] == 1:
                _set_active_year(conn, cur.lastrowid)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ApiError(friendly_integrity(exc), 409)
    return list_rows(conn, name, {}, cur.lastrowid)[0]


def update_row(conn, name, row_id, body):
    spec = RESOURCES[name]
    existing = conn.execute(f'SELECT * FROM {spec["table"]} WHERE id = ?', (row_id,)).fetchone()
    if existing is None:
        raise ApiError("Élément introuvable.", 404)
    data = {}
    for field, (kind, required, _default) in spec["fields"].items():
        if field in body:
            value = coerce(field, kind, body[field])
            if required and kind == "str" and not value:
                raise ApiError(f'{LABELS.get(field, field)} est obligatoire.')
            data[field] = value
    if name == "students" and "matricule" in data and not data["matricule"]:
        del data["matricule"]
    if not data:
        return list_rows(conn, name, {}, row_id)[0]
    _cross_checks(conn, name, data, dict(existing))
    try:
        conn.execute(
            f'UPDATE {spec["table"]} SET {", ".join(f"{k} = ?" for k in data)} WHERE id = ?',
            [*data.values(), row_id],
        )
        if name == "years" and data.get("active"):
            _set_active_year(conn, row_id)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ApiError(friendly_integrity(exc), 409)
    return list_rows(conn, name, {}, row_id)[0]


def delete_row(conn, name, row_id):
    spec = RESOURCES[name]
    cur = conn.execute(f'DELETE FROM {spec["table"]} WHERE id = ?', (row_id,))
    if cur.rowcount == 0:
        conn.rollback()
        raise ApiError("Élément introuvable.", 404)
    if name == "years" and not conn.execute("SELECT 1 FROM years WHERE active = 1").fetchone():
        newest = conn.execute("SELECT id FROM years ORDER BY name DESC LIMIT 1").fetchone()
        if newest:
            _set_active_year(conn, newest["id"])
    conn.commit()


# --------------------------------------------------------------------------
# Actions spécifiques
# --------------------------------------------------------------------------
PRESETS = {"trimestre": ("Trimestre", 3), "semestre": ("Semestre", 2)}


def create_period_preset(conn, year_id, kind):
    if kind not in PRESETS:
        raise ApiError("Type de période inconnu.")
    if not conn.execute("SELECT 1 FROM years WHERE id = ?", (year_id,)).fetchone():
        raise ApiError("Année introuvable.", 404)
    label, count = PRESETS[kind]
    base = conn.execute("SELECT COALESCE(MAX(position), 0) FROM periods WHERE year_id = ?", (year_id,)).fetchone()[0]
    for i in range(1, count + 1):
        conn.execute(
            "INSERT OR IGNORE INTO periods(year_id, name, weight, position) VALUES (?, ?, 1, ?)",
            (year_id, f"{label} {i}", base + i),
        )
    conn.commit()


def copy_class_subjects(conn, class_id, from_class_id):
    if class_id == from_class_id:
        raise ApiError("Choisissez une autre classe source.")
    conn.execute(
        """INSERT OR IGNORE INTO class_subjects(class_id, subject_id, coef, teacher)
           SELECT ?, subject_id, coef, teacher FROM class_subjects WHERE class_id = ?""",
        (class_id, from_class_id),
    )
    conn.commit()


def get_grades(conn, evaluation_id):
    ev = list_rows(conn, "evaluations", {}, evaluation_id)
    if not ev:
        raise ApiError("Évaluation introuvable.", 404)
    ev = ev[0]
    rows = conn.execute(
        """SELECT st.id AS student_id, st.matricule, st.last_name, st.first_name, g.score, COALESCE(g.absent, 0) AS absent
           FROM students st LEFT JOIN grades g ON g.student_id = st.id AND g.evaluation_id = ?
           WHERE st.class_id = ? ORDER BY st.last_name COLLATE NOCASE, st.first_name COLLATE NOCASE""",
        (evaluation_id, ev["class_id"]),
    ).fetchall()
    students = [{**dict(r), "name": f'{r["last_name"].upper()} {r["first_name"]}'} for r in rows]
    return {"evaluation": ev, "students": students}


def save_grades(conn, evaluation_id, body):
    data = get_grades(conn, evaluation_id)
    max_score = data["evaluation"]["max_score"]
    valid_ids = {s["student_id"] for s in data["students"]}
    entries = body.get("grades")
    if not isinstance(entries, list):
        raise ApiError("Format de notes invalide.")
    clean = []
    for entry in entries:
        try:
            sid = int(entry["student_id"])
        except (KeyError, TypeError, ValueError):
            raise ApiError("Élève invalide.")
        if sid not in valid_ids:
            raise ApiError("Un élève n'appartient pas à cette classe.")
        absent = bool(entry.get("absent"))
        score = entry.get("score")
        if score in (None, "") or absent:
            score = None
        else:
            score = coerce("score", "num", score)
            if score < 0 or score > max_score:
                raise ApiError(f"Une note doit être comprise entre 0 et {max_score:g}.")
        clean.append((sid, score, absent))
    for sid, score, absent in clean:
        if score is None and not absent:
            conn.execute("DELETE FROM grades WHERE evaluation_id = ? AND student_id = ?", (evaluation_id, sid))
        else:
            conn.execute(
                """INSERT INTO grades(evaluation_id, student_id, score, absent) VALUES (?, ?, ?, ?)
                   ON CONFLICT(evaluation_id, student_id) DO UPDATE SET score = excluded.score, absent = excluded.absent""",
                (evaluation_id, sid, score, int(absent)),
            )
    conn.commit()
    return get_grades(conn, evaluation_id)


# --------------------------------------------------------------------------
# Import CSV des élèves
# --------------------------------------------------------------------------
HEADER_ALIASES = {
    "matricule": "matricule", "mat": "matricule", "id": "matricule",
    "nom": "last_name", "nom de famille": "last_name", "last_name": "last_name", "lastname": "last_name",
    "prenom": "first_name", "prénom": "first_name", "prenoms": "first_name", "prénoms": "first_name",
    "first_name": "first_name", "firstname": "first_name",
    "sexe": "sex", "genre": "sex", "sex": "sex",
    "naissance": "birth_date", "date_naissance": "birth_date", "date de naissance": "birth_date",
    "birth_date": "birth_date", "né le": "birth_date", "née le": "birth_date",
}
POSITIONAL = ["matricule", "last_name", "first_name", "sex", "birth_date"]


def _normalize_date(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if not value:
        return ""
    raise ValueError(f"date illisible « {value} »")


def import_students(conn, class_id, text):
    if not conn.execute("SELECT 1 FROM classes WHERE id = ?", (class_id,)).fetchone():
        raise ApiError("Classe introuvable.", 404)
    text = (text or "").lstrip("﻿")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ApiError("Le fichier est vide.")
    delim = max(";,\t", key=lines[0].count)
    rows = list(csv.reader(lines, delimiter=delim))
    header = [c.strip().lower() for c in rows[0]]
    mapped = [HEADER_ALIASES.get(c) for c in header]
    if "last_name" in mapped or "matricule" in mapped:
        columns, rows = mapped, rows[1:]
        first_line = 2
    else:
        columns, first_line = POSITIONAL, 1
    created = updated = 0
    errors = []
    for i, row in enumerate(rows, start=first_line):
        rec = {col: (row[j].strip() if j < len(row) else "") for j, col in enumerate(columns) if col}
        try:
            if not rec.get("last_name") or not rec.get("first_name"):
                raise ValueError("nom et prénom obligatoires")
            sex = coerce("sex", "sex", rec.get("sex", ""))
            birth = _normalize_date(rec.get("birth_date", ""))
            mat = rec.get("matricule", "")
            existing = conn.execute("SELECT id, class_id FROM students WHERE matricule = ?", (mat,)).fetchone() if mat else None
            if existing:
                if existing["class_id"] != class_id:
                    raise ValueError(f"matricule {mat} déjà utilisé dans une autre classe")
                conn.execute(
                    """UPDATE students SET last_name=?, first_name=?, sex=COALESCE(NULLIF(?, ''), sex),
                       birth_date=COALESCE(NULLIF(?, ''), birth_date) WHERE id=?""",
                    (rec["last_name"], rec["first_name"], sex, birth, existing["id"]),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO students(matricule, last_name, first_name, sex, birth_date, class_id) VALUES (?,?,?,?,?,?)",
                    (mat or _next_matricule(conn), rec["last_name"], rec["first_name"], sex, birth, class_id),
                )
                created += 1
        except (ValueError, ApiError) as exc:
            errors.append(f"Ligne {i} : {exc}")
    conn.commit()
    return {"created": created, "updated": updated, "errors": errors}


# --------------------------------------------------------------------------
# Rapports
# --------------------------------------------------------------------------
def report(conn, class_id, period):
    period_id = None if period in (None, "", "annual") else int(period)
    rep = calc.class_report(conn, class_id, period_id)
    if rep is None:
        raise ApiError("Classe ou période introuvable.", 404)
    return rep


def _fmt(value):
    return "" if value is None else f"{value:.2f}".replace(".", ",")


def report_csv(conn, class_id, period):
    rep = report(conn, class_id, period)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow([rep["settings"]["school_name"]])
    w.writerow([f'Classe {rep["class"]["name"]}', rep["class"]["year"], rep["period"]["name"]])
    w.writerow([])
    head = ["Rang", "Matricule", "Nom", "Prénom"] + [s["name"] for s in rep["subjects"]]
    if rep["period"]["annual"]:
        head += [p["name"] for p in rep["periods"]]
    w.writerow(head + ["Moyenne", "Mention"])
    w.writerow(["", "", "", "Coefficient"] + [_fmt(s["coef"]) for s in rep["subjects"]])
    for st in sorted(rep["students"], key=lambda s: (s["rank"] is None, s["rank"] or 0, s["name"])):
        line = [st["rank"] or "", st["matricule"], st["last_name"], st["first_name"]]
        line += [_fmt(st["subjects"].get(str(s["id"]))) for s in rep["subjects"]]
        if rep["period"]["annual"]:
            line += [_fmt(st["period_averages"].get(str(p["id"]))) for p in rep["periods"]]
        w.writerow(line + [_fmt(st["average"]), st["mention"]])
    w.writerow([])
    stats = rep["stats"]
    w.writerow(["Moyenne de classe", _fmt(stats["avg"])])
    w.writerow(["Plus forte moyenne", _fmt(stats["max"])])
    w.writerow(["Plus faible moyenne", _fmt(stats["min"])])
    w.writerow(["Taux de réussite (%)", _fmt(stats["pass_rate"])])
    return "﻿" + out.getvalue()


def dashboard(conn, year_id):
    if year_id is None:
        row = conn.execute("SELECT id FROM years WHERE active = 1").fetchone()
        year_id = row["id"] if row else None
    if year_id is None:
        return {"year_id": None, "counts": {}, "classes": [], "top": []}
    counts = {
        "students": conn.execute(
            "SELECT COUNT(*) FROM students s JOIN classes c ON c.id = s.class_id WHERE c.year_id = ?", (year_id,)
        ).fetchone()[0],
        "classes": conn.execute("SELECT COUNT(*) FROM classes WHERE year_id = ?", (year_id,)).fetchone()[0],
        "tracks": conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
        "subjects": conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0],
        "evaluations": conn.execute(
            """SELECT COUNT(*) FROM evaluations e JOIN periods p ON p.id = e.period_id WHERE p.year_id = ?""",
            (year_id,),
        ).fetchone()[0],
    }
    classes, top = [], []
    for c in list_rows(conn, "classes", {"year_id": str(year_id)}):
        current = conn.execute(
            """SELECT p.id, p.name FROM periods p WHERE p.year_id = ? AND EXISTS (
                 SELECT 1 FROM evaluations e JOIN grades g ON g.evaluation_id = e.id WHERE e.period_id = p.id
                 AND e.class_subject_id IN (SELECT id FROM class_subjects WHERE class_id = ?))
               ORDER BY p.position DESC, p.id DESC LIMIT 1""",
            (year_id, c["id"]),
        ).fetchone()
        entry = {"id": c["id"], "name": c["name"], "track": c["track_name"], "students": c["student_count"],
                 "period": None, "avg": None, "pass_rate": None, "min": None, "max": None}
        if current:
            rep = calc.class_report(conn, c["id"], current["id"])
            entry.update(period=current["name"], avg=rep["stats"]["avg"], pass_rate=rep["stats"]["pass_rate"],
                         min=rep["stats"]["min"], max=rep["stats"]["max"])
            for s in rep["students"]:
                if s["average"] is not None:
                    top.append({"name": s["name"], "class": c["name"], "average": s["average"], "period": current["name"]})
        classes.append(entry)
    top.sort(key=lambda t: -t["average"])
    return {"year_id": year_id, "counts": counts, "classes": classes, "top": top[:5]}


def update_settings(conn, body):
    import json

    current = get_settings(conn)
    new = {}
    if "school_name" in body:
        new["school_name"] = str(body["school_name"]).strip()[:200] or current["school_name"]
    if "scale" in body:
        scale = coerce("scale", "num", body["scale"])
        if scale <= 0 or scale > 1000:
            raise ApiError("Le barème doit être compris entre 0 et 1000.")
        new["scale"] = scale
    scale = new.get("scale", current["scale"])
    if "pass_mark" in body:
        pm = coerce("pass_mark", "num", body["pass_mark"])
        if pm < 0 or pm > scale:
            raise ApiError("La moyenne de passage doit être comprise entre 0 et le barème.")
        new["pass_mark"] = pm
    if "mentions" in body:
        ms = body["mentions"]
        if not isinstance(ms, list) or not ms:
            raise ApiError("Liste de mentions invalide.")
        cleaned = [{"min": coerce("min", "num", m.get("min")), "label": str(m.get("label", "")).strip()[:50]} for m in ms]
        if any(not m["label"] for m in cleaned):
            raise ApiError("Chaque mention doit avoir un libellé.")
        new["mentions"] = cleaned
    for key, value in new.items():
        conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, json.dumps(value)))
    conn.commit()
    return get_settings(conn)
