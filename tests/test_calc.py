import unittest

from jiji import api, calc
from jiji.db import connect, init_db


class PureHelpers(unittest.TestCase):
    def test_weighted_mean(self):
        self.assertAlmostEqual(calc.weighted_mean([(10, 1), (16, 2)]), 14)
        self.assertIsNone(calc.weighted_mean([]))
        self.assertIsNone(calc.weighted_mean([(None, 3)]))

    def test_rank_ties(self):
        self.assertEqual(calc.rank_values([15, 12, 15, None, 9]), [1, 3, 1, None, 4])

    def test_rank_uses_rounded_values(self):
        self.assertEqual(calc.rank_values([12.004, 12.001]), [1, 1])

    def test_mention(self):
        ms = [{"min": 16, "label": "TB"}, {"min": 10, "label": "P"}, {"min": 0, "label": "I"}]
        self.assertEqual(calc.mention(17, ms), "TB")
        self.assertEqual(calc.mention(10, ms), "P")
        self.assertEqual(calc.mention(9.99, ms), "I")
        self.assertEqual(calc.mention(None, ms), "")


class Scenario(unittest.TestCase):
    """Une classe, 2 matières (coef 3 et 1), 2 trimestres, 3 élèves."""

    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        c = self.conn
        self.year = api.create_row(c, "years", {"name": "2025-2026"})["id"]
        api.create_period_preset(c, self.year, "trimestre")
        self.p1, self.p2, self.p3 = [p["id"] for p in api.list_rows(c, "periods", {"year_id": str(self.year)})]
        track = api.create_row(c, "tracks", {"name": "Sciences"})["id"]
        self.cls = api.create_row(c, "classes", {"year_id": self.year, "track_id": track, "name": "2nde S1"})["id"]
        maths = api.create_row(c, "subjects", {"name": "Maths"})["id"]
        fr = api.create_row(c, "subjects", {"name": "Français"})["id"]
        self.cs_m = api.create_row(c, "class-subjects", {"class_id": self.cls, "subject_id": maths, "coef": 3})["id"]
        self.cs_f = api.create_row(c, "class-subjects", {"class_id": self.cls, "subject_id": fr, "coef": 1})["id"]
        self.s = [api.create_row(c, "students", {"last_name": n, "first_name": "X", "class_id": self.cls})["id"]
                  for n in ("Alpha", "Bravo", "Charlie")]

    def evaluation(self, cs, period, title, scores, max_score=20, weight=1):
        ev = api.create_row(self.conn, "evaluations", {"class_subject_id": cs, "period_id": period, "title": title,
                                                        "max_score": max_score, "weight": weight})
        api.save_grades(self.conn, ev["id"], {"grades": [
            {"student_id": sid, **({"absent": True} if v == "abs" else {"score": v})} for sid, v in zip(self.s, scores)]})
        return ev

    def student(self, rep, idx):
        return next(r for r in rep["students"] if r["id"] == self.s[idx])

    def test_period_report(self):
        self.evaluation(self.cs_m, self.p1, "DS1", [10, 20, 5])
        self.evaluation(self.cs_m, self.p1, "DS2", [14, 20, 5], weight=2)   # Alpha: (10 + 28)/3
        self.evaluation(self.cs_f, self.p1, "Dictée", [8, 12, None])
        rep = calc.class_report(self.conn, self.cls, self.p1)
        a = self.student(rep, 0)
        self.assertAlmostEqual(a["subjects"][str(self.cs_m)], 12.67, places=2)
        self.assertAlmostEqual(a["average"], round((38 / 3 * 3 + 8) / 4, 2), places=2)
        # Charlie n'a pas de note en français : seule les maths comptent
        self.assertEqual(self.student(rep, 2)["average"], 5.0)
        self.assertEqual([self.student(rep, i)["rank"] for i in range(3)], [2, 1, 3])
        self.assertEqual(rep["stats"]["count"], 3)

    def test_scale_and_absence(self):
        self.evaluation(self.cs_m, self.p1, "QCM", [5, "abs", 10], max_score=10)  # /10 -> /20
        rep = calc.class_report(self.conn, self.cls, self.p1)
        self.assertEqual(self.student(rep, 0)["average"], 10.0)
        self.assertIsNone(self.student(rep, 1)["average"])       # absent = non pénalisé, pas de moyenne
        self.assertIsNone(self.student(rep, 1)["rank"])
        self.assertEqual(self.student(rep, 2)["average"], 20.0)

    def test_annual(self):
        self.evaluation(self.cs_m, self.p1, "T1", [10, 10, 10])
        self.evaluation(self.cs_m, self.p2, "T2", [16, 10, 10])
        rep = calc.class_report(self.conn, self.cls, None)
        self.assertEqual(self.student(rep, 0)["average"], 13.0)
        self.assertEqual(self.student(rep, 0)["period_averages"][str(self.p1)], 10.0)
        self.assertIsNone(self.student(rep, 0)["period_averages"][str(self.p3)])
        self.assertEqual(self.student(rep, 0)["rank"], 1)

    def test_period_weight_in_annual(self):
        api.update_row(self.conn, "periods", self.p2, {"weight": 2})
        self.evaluation(self.cs_m, self.p1, "T1", [10, 10, 10])
        self.evaluation(self.cs_m, self.p2, "T2", [16, 10, 10])
        rep = calc.class_report(self.conn, self.cls, None)
        self.assertEqual(self.student(rep, 0)["average"], 14.0)

    def test_pass_rate_and_stats(self):
        self.evaluation(self.cs_m, self.p1, "DS", [9.99, 10, 18])
        stats = calc.class_report(self.conn, self.cls, self.p1)["stats"]
        self.assertEqual(stats["passed"], 2)   # 9.99 arrondi à 9.99 < 10
        self.assertEqual((stats["min"], stats["max"]), (9.99, 18.0))

    def test_empty_class(self):
        empty = api.create_row(self.conn, "classes", {"year_id": self.year, "name": "Vide"})["id"]
        rep = calc.class_report(self.conn, empty, self.p1)
        self.assertEqual(rep["students"], [])
        self.assertIsNone(rep["stats"]["avg"])

    def test_unknown(self):
        self.assertIsNone(calc.class_report(self.conn, 999, None))
        self.assertIsNone(calc.class_report(self.conn, self.cls, 999))


if __name__ == "__main__":
    unittest.main()
