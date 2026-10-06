"""Moteur de calcul des moyennes, rangs, mentions et statistiques.

Règles appliquées :
* Une note est ramenée sur le barème de l'établissement (20 par défaut)
  puis pondérée par le poids de l'évaluation : moyenne de matière =
  Σ(note/barème × échelle × poids) / Σ(poids).
* Un élève absent (ou sans note) à une évaluation n'est pas pénalisé :
  l'évaluation est ignorée pour lui.
* Moyenne générale = Σ(moyenne matière × coefficient) / Σ(coefficients),
  uniquement sur les matières où l'élève a au moins une note.
* Moyenne annuelle = moyenne des moyennes de période pondérées par le
  poids de chaque période (matière par matière, puis générale).
* Rang « sportif » : les ex æquo partagent le même rang (1, 1, 3…),
  comparaison sur la moyenne arrondie à 2 décimales.
"""
from .db import get_settings

PRECISION = 2


def rnd(value):
    return None if value is None else round(value + 0.0, PRECISION)


def weighted_mean(pairs):
    """pairs: itérable de (valeur, poids). Retourne None si aucun poids."""
    total = weight = 0.0
    for value, w in pairs:
        if value is None:
            continue
        total += value * w
        weight += w
    return total / weight if weight else None


def rank_values(values):
    """Rang de chaque valeur (None -> None). Plus grand = meilleur rang."""
    scored = sorted((rnd(v) for v in values if v is not None), reverse=True)
    out = []
    for v in values:
        out.append(None if v is None else scored.index(rnd(v)) + 1)
    return out


def mention(avg, mentions):
    if avg is None:
        return ""
    for m in sorted(mentions, key=lambda m: -m["min"]):
        if avg >= m["min"]:
            return m["label"]
    return ""


def _stats(values, pass_mark):
    vals = [v for v in values if v is not None]
    if not vals:
        return {"count": 0, "avg": None, "min": None, "max": None, "passed": 0, "pass_rate": None}
    passed = sum(1 for v in vals if rnd(v) >= pass_mark)
    return {
        "count": len(vals),
        "avg": rnd(sum(vals) / len(vals)),
        "min": rnd(min(vals)),
        "max": rnd(max(vals)),
        "passed": passed,
        "pass_rate": rnd(100.0 * passed / len(vals)),
    }


def _load_class(conn, class_id):
    cls = conn.execute(
        """SELECT c.id, c.name, c.year_id, y.name AS year, t.name AS track
           FROM classes c JOIN years y ON y.id = c.year_id
           LEFT JOIN tracks t ON t.id = c.track_id WHERE c.id = ?""",
        (class_id,),
    ).fetchone()
    if cls is None:
        return None
    subjects = conn.execute(
        """SELECT cs.id, s.name, s.code, cs.coef, cs.teacher
           FROM class_subjects cs JOIN subjects s ON s.id = cs.subject_id
           WHERE cs.class_id = ? ORDER BY s.name COLLATE NOCASE""",
        (class_id,),
    ).fetchall()
    students = conn.execute(
        """SELECT id, matricule, last_name, first_name, sex, birth_date
           FROM students WHERE class_id = ?
           ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE""",
        (class_id,),
    ).fetchall()
    return dict(cls), [dict(s) for s in subjects], [dict(s) for s in students]


def _period_matrix(conn, class_id, period_id, subjects, students, scale):
    """Moyennes par matière et élève pour une période : {student_id: {cs_id: avg}}."""
    rows = conn.execute(
        """SELECT e.class_subject_id AS cs, g.student_id AS st, g.score, e.max_score, e.weight
           FROM evaluations e
           JOIN class_subjects cs ON cs.id = e.class_subject_id
           JOIN grades g ON g.evaluation_id = e.id
           WHERE cs.class_id = ? AND e.period_id = ? AND g.absent = 0 AND g.score IS NOT NULL""",
        (class_id, period_id),
    ).fetchall()
    acc = {}
    for r in rows:
        acc.setdefault((r["st"], r["cs"]), []).append((r["score"] / r["max_score"] * scale, r["weight"]))
    matrix = {s["id"]: {} for s in students}
    for (st, cs), pairs in acc.items():
        if st in matrix:
            matrix[st][cs] = weighted_mean(pairs)
    return matrix


def _general(subject_avgs, coefs):
    return weighted_mean((avg, coefs[cs]) for cs, avg in subject_avgs.items() if avg is not None)


def class_report(conn, class_id, period_id=None):
    """Rapport complet d'une classe. period_id=None → moyenne annuelle."""
    loaded = _load_class(conn, class_id)
    if loaded is None:
        return None
    cls, subjects, students = loaded
    settings = get_settings(conn)
    scale, pass_mark, mentions = settings["scale"], settings["pass_mark"], settings["mentions"]
    coefs = {s["id"]: s["coef"] for s in subjects}
    periods = [
        dict(p)
        for p in conn.execute(
            "SELECT id, name, weight, position FROM periods WHERE year_id = ? ORDER BY position, id",
            (cls["year_id"],),
        )
    ]

    per_period = {p["id"]: _period_matrix(conn, class_id, p["id"], subjects, students, scale) for p in periods}
    if period_id is not None:
        selected = next((p for p in periods if p["id"] == period_id), None)
        if selected is None:
            return None
        matrix = per_period[period_id]
        period_info = {"id": selected["id"], "name": selected["name"], "annual": False}
    else:
        matrix = {}
        for s in students:
            matrix[s["id"]] = {
                sub["id"]: weighted_mean(
                    (per_period[p["id"]][s["id"]].get(sub["id"]), p["weight"]) for p in periods
                )
                for sub in subjects
            }
        period_info = {"id": None, "name": "Année", "annual": True}

    rows = []
    for s in students:
        subj_avgs = matrix[s["id"]]
        if period_info["annual"]:
            p_avgs = {p["id"]: _general(per_period[p["id"]][s["id"]], coefs) for p in periods}
            average = weighted_mean((p_avgs[p["id"]], p["weight"]) for p in periods)
        else:
            p_avgs = {}
            average = _general(subj_avgs, coefs)
        rows.append(
            {
                **s,
                "name": f'{s["last_name"].upper()} {s["first_name"]}'.strip(),
                "subjects": {str(k): rnd(v) for k, v in subj_avgs.items()},
                "period_averages": {str(k): rnd(v) for k, v in p_avgs.items()},
                "average": rnd(average),
                "mention": mention(rnd(average), mentions),
                "passed": None if average is None else rnd(average) >= pass_mark,
            }
        )
    for row, rk in zip(rows, rank_values([r["average"] for r in rows])):
        row["rank"] = rk

    subject_out = []
    for sub in subjects:
        st = _stats([matrix[s["id"]].get(sub["id"]) for s in students], pass_mark)
        subject_out.append({**sub, "stats": st})
    stats = _stats([r["average"] for r in rows], pass_mark)
    stats["students"] = len(students)

    return {
        "class": cls,
        "period": period_info,
        "periods": periods,
        "subjects": subject_out,
        "students": rows,
        "stats": stats,
        "settings": {
            "school_name": settings["school_name"],
            "pass_mark": pass_mark,
            "scale": scale,
            "mentions": mentions,
        },
    }
