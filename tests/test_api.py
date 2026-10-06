import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from jiji.server import make_server


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, headers=None, raw=False):
        h = {"X-Requested-With": "jiji", "Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, method=method, headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(req) as r:
                data = r.read()
                return r.status, (data if raw else json.loads(data))
        except urllib.error.HTTPError as e:
            data = e.read()
            return e.code, (data if raw else json.loads(data))


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = make_server(str(Path(cls.tmp.name) / "t.db"), "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_full_flow(self):
        c = Client(self.base)
        self.assertEqual(c.call("GET", "/api/years")[0], 401)
        st, status = c.call("GET", "/api/status")
        self.assertTrue(status["setup_needed"])
        self.assertEqual(c.call("POST", "/api/setup", {"username": "admin", "password": "123"})[0], 400)
        self.assertEqual(c.call("POST", "/api/setup", {"username": "admin", "password": "secret1", "school_name": "Lycée Test"})[0], 200)
        self.assertEqual(c.call("POST", "/api/setup", {"username": "x", "password": "secret1"})[0], 403)
        self.assertEqual(c.call("GET", "/api/status")[1]["school_name"], "Lycée Test")

        # CSRF : sans l'en-tête, les écritures sont refusées
        req = urllib.request.Request(self.base + "/api/years", method="POST", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            c.opener.open(req)
        self.assertEqual(ctx.exception.code, 403)

        st, year = c.call("POST", "/api/years", {"name": "2025-2026"})
        self.assertEqual((st, year["active"]), (200, 1))
        self.assertEqual(c.call("POST", "/api/years", {"name": "2025-2026"})[0], 409)
        self.assertEqual(len(c.call("POST", f"/api/years/{year['id']}/periods/preset", {"kind": "semestre"})[1]), 2)
        periods = c.call("GET", f"/api/periods?year_id={year['id']}")[1]
        _, track = c.call("POST", "/api/tracks", {"name": "Lettres"})
        _, cls = c.call("POST", "/api/classes", {"year_id": year["id"], "track_id": track["id"], "name": "1ère L"})
        _, maths = c.call("POST", "/api/subjects", {"name": "Maths"})
        _, cs = c.call("POST", "/api/class-subjects", {"class_id": cls["id"], "subject_id": maths["id"], "coef": "2,5"})
        self.assertEqual(cs["coef"], 2.5)
        self.assertEqual(c.call("POST", "/api/class-subjects", {"class_id": cls["id"], "subject_id": maths["id"]})[0], 409)
        self.assertEqual(c.call("POST", "/api/class-subjects", {"class_id": cls["id"], "subject_id": maths["id"], "coef": 0})[0], 400)

        csv_text = "matricule;nom;prénom;sexe;naissance\nA1;Diallo;Awa;F;03/04/2009\n;Ba;Omar;M;2008-11-30\nA1;Diallo;Awa;F;\n;;;\n"
        _, res = c.call("POST", f"/api/classes/{cls['id']}/students/import", {"csv": csv_text})
        self.assertEqual((res["created"], res["updated"], len(res["errors"])), (2, 1, 1))
        students = c.call("GET", f"/api/students?class_id={cls['id']}")[1]
        self.assertEqual([s["last_name"] for s in students], ["Ba", "Diallo"])
        self.assertEqual(c.call("GET", "/api/students?q=awa")[1][0]["birth_date"], "2009-04-03")

        _, ev = c.call("POST", "/api/evaluations", {"class_subject_id": cs["id"], "period_id": periods[0]["id"],
                                                    "title": "DS 1", "max_score": 20})
        grades = [{"student_id": students[0]["id"], "score": "15,5"}, {"student_id": students[1]["id"], "absent": True}]
        self.assertEqual(c.call("PUT", f"/api/evaluations/{ev['id']}/grades", {"grades": [{"student_id": students[0]["id"], "score": 21}]})[0], 400)
        self.assertEqual(c.call("PUT", f"/api/evaluations/{ev['id']}/grades", {"grades": [{"student_id": 9999, "score": 5}]})[0], 400)
        st, saved = c.call("PUT", f"/api/evaluations/{ev['id']}/grades", {"grades": grades})
        self.assertEqual(st, 200)
        self.assertEqual(saved["students"][0]["score"], 15.5)
        self.assertEqual(c.call("GET", f"/api/evaluations?class_id={cls['id']}")[1][0]["graded_count"], 2)
        # réduire le barème en dessous d'une note existante est refusé
        self.assertEqual(c.call("PUT", f"/api/evaluations/{ev['id']}", {"max_score": 10})[0], 400)

        _, rep = c.call("GET", f"/api/classes/{cls['id']}/report?period={periods[0]['id']}")
        top = next(s for s in rep["students"] if s["last_name"] == "Ba")
        self.assertEqual((top["average"], top["rank"], top["mention"]), (15.5, 1, "Bien"))
        _, annual = c.call("GET", f"/api/classes/{cls['id']}/report?period=annual")
        self.assertTrue(annual["period"]["annual"])
        status, csv_out = c.call("GET", f"/api/classes/{cls['id']}/report.csv?period=annual", raw=True)
        self.assertIn("15,50".encode(), csv_out)

        dash = c.call("GET", "/api/dashboard")[1]
        self.assertEqual(dash["counts"]["students"], 2)
        self.assertEqual(dash["top"][0]["average"], 15.5)

        self.assertEqual(c.call("PUT", "/api/settings", {"pass_mark": 25})[0], 400)
        self.assertEqual(c.call("PUT", "/api/settings", {"pass_mark": 12})[0], 200)
        self.assertEqual(c.call("GET", "/api/backup", raw=True)[1][:6], b"SQLite")

        # suppression en cascade
        self.assertEqual(c.call("DELETE", f"/api/classes/{cls['id']}")[0], 200)
        self.assertEqual(c.call("GET", "/api/students")[1], [])
        self.assertEqual(c.call("GET", "/api/nimportequoi")[0], 404)

        # mot de passe + déconnexion
        self.assertEqual(c.call("POST", "/api/password", {"old": "bad", "new": "newsecret"})[0], 403)
        self.assertEqual(c.call("POST", "/api/password", {"old": "secret1", "new": "newsecret"})[0], 200)
        c.call("POST", "/api/logout", {})
        self.assertEqual(c.call("GET", "/api/years")[0], 401)
        self.assertEqual(Client(self.base).call("POST", "/api/login", {"username": "admin", "password": "secret1"})[0], 401)
        self.assertEqual(c.call("POST", "/api/login", {"username": "admin", "password": "newsecret"})[0], 200)

    def test_static_and_host_check(self):
        c = Client(self.base)
        req = urllib.request.Request(self.base + "/")
        self.assertIn(b"Jiji", urllib.request.urlopen(req).read())
        self.assertEqual(c.call("GET", "/../server.py")[0], 404)
        bad = urllib.request.Request(self.base + "/api/status", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad)
        self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
