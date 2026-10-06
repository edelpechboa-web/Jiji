"""Génère une base de démonstration : python3 -m jiji.demo demo.db  (compte : admin / demo123)."""
import random
import sys

from . import api
from .db import connect, init_db
from .server import hash_password

NAMES = [("Diallo", "Awa"), ("Ba", "Omar"), ("Traoré", "Mamadou"), ("Sow", "Fatou"), ("Camara", "Ibrahima"),
         ("Keita", "Aminata"), ("Sy", "Moussa"), ("Cissé", "Mariam"), ("Fall", "Cheikh"), ("Ndiaye", "Khady"),
         ("Barry", "Alpha"), ("Touré", "Salimata")]


def build(path):
    conn = connect(path)
    init_db(conn)
    salt, digest = hash_password("demo123")
    conn.execute("INSERT OR IGNORE INTO users(username, salt, pw_hash) VALUES ('admin', ?, ?)", (salt, digest))
    api.update_settings(conn, {"school_name": "Lycée Démonstration"})
    rnd = random.Random(42)
    year = api.create_row(conn, "years", {"name": "2025-2026", "active": True})["id"]
    api.create_period_preset(conn, year, "trimestre")
    periods = [p["id"] for p in api.list_rows(conn, "periods", {"year_id": str(year)})]
    tracks = {n: api.create_row(conn, "tracks", {"name": n, "code": n[0]})["id"] for n in ("Sciences", "Lettres")}
    subjects = {n: api.create_row(conn, "subjects", {"name": n, "code": n[:4].upper()})["id"]
                for n in ("Mathématiques", "Français", "Physique-Chimie", "Histoire-Géo", "Anglais", "SVT", "Philosophie")}
    plan = {"2nde S1": ("Sciences", {"Mathématiques": 4, "Physique-Chimie": 3, "SVT": 2, "Français": 3, "Anglais": 2, "Histoire-Géo": 2}),
            "2nde L1": ("Lettres", {"Français": 4, "Histoire-Géo": 3, "Anglais": 3, "Philosophie": 3, "Mathématiques": 2})}
    for cname, (track, subs) in plan.items():
        cid = api.create_row(conn, "classes", {"year_id": year, "track_id": tracks[track], "name": cname})["id"]
        cs_ids = [api.create_row(conn, "class-subjects", {"class_id": cid, "subject_id": subjects[s], "coef": c})["id"] for s, c in subs.items()]
        students = [api.create_row(conn, "students", {"last_name": ln, "first_name": fn, "class_id": cid, "sex": rnd.choice("MF"),
                                                      "birth_date": f"{rnd.randint(2008, 2010)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"})["id"] for ln, fn in NAMES]
        level = {sid: rnd.uniform(7, 16) for sid in students}
        for pid in periods[:2]:
            for cs in cs_ids:
                for title, w in (("Devoir 1", 1), ("Devoir 2", 1), ("Composition", 2)):
                    ev = api.create_row(conn, "evaluations", {"class_subject_id": cs, "period_id": pid, "title": title, "weight": w, "date": "2025-11-15"})
                    api.save_grades(conn, ev["id"], {"grades": [
                        {"student_id": sid, "score": round(min(20, max(0, rnd.gauss(level[sid], 2.5))) * 2) / 2} if rnd.random() > 0.05 else {"student_id": sid, "absent": True}
                        for sid in students]})
    conn.close()


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
    print("Base de démonstration créée. Identifiants : admin / demo123")
