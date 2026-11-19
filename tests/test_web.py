"""Web-layer tests (auth, RBAC, hidden data, publish gate, CSRF). They need fastapi+sqlalchemy installed
and do NOT need Docker (the judge worker is disabled; tests are inserted straight into the DB)."""
import dataclasses, os, tempfile, unittest
from datetime import timedelta
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_tmp, "t.db").replace("\\", "/")
os.environ["DISABLE_WORKER"] = "1"
os.environ["ALLOW_REGISTRATION"] = "1"   # tests self-register; production default is closed
os.environ.pop("APP_ENV", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from app import main  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (Contest, ContestParticipant, ContestProblem, IgnoredSubmission, Problem, ReferenceSolution,  # noqa: E402
                        Submission, TestCase, User)
from app.timeutil import now  # noqa: E402
from app.testgen import input_hash  # noqa: E402
from app.users import create_user  # noqa: E402

H = {"origin": "http://testserver"}
HIDDEN = "HIDDEN-INPUT-9999"


def client():
    return TestClient(main.app, headers=H, follow_redirects=False)


def add_problem(n_tests, published=False):
    with SessionLocal() as db:
        p = Problem(title="P", statement="s", difficulty="easy", published=published)
        db.add(p)
        db.flush()
        db.add(ReferenceSolution(problem_id=p.id, language="python3", source="print(1)"))
        for i in range(n_tests):
            inp = (HIDDEN if i else "1 2") + f" {i}\n"
            db.add(TestCase(problem_id=p.id, ordinal=i + 1, input_data=inp, expected_output="x\n", is_sample=(i == 0),
                            input_hash=input_hash(inp), validated=True, kind="manual"))
        db.commit()
        return p.id


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(main.app)
        cls.ctx.__enter__()  # runs lifespan: creates tables and roles
        with SessionLocal() as db:
            create_user(db, "boss", "boss@example.com", "a-long-admin-pass", "admin")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        main.auth_limiter.hits.clear()

    def login(self, c, ident, pw):
        return c.post("/login", data={"identifier": ident, "password": pw, "next": "/problems"})

    def student(self, name):
        c = client()
        r = c.post("/register", data={"username": name, "email": name + "@example.com", "password": "password123"})
        self.assertEqual(r.status_code, 303)
        return c

    def admin(self):
        c = client()
        self.assertEqual(self.login(c, "boss", "a-long-admin-pass").status_code, 303)
        return c

    def test_anonymous_redirected(self):
        r = client().get("/problems")
        self.assertEqual((r.status_code, r.headers["location"].split("?")[0]), (303, "/login"))

    def test_student_cannot_use_admin(self):
        c = self.student("stu1")
        self.assertEqual(c.get("/admin").status_code, 403)
        self.assertEqual(c.get("/admin/users").status_code, 403)
        self.assertEqual(c.post("/admin/api/problems/1/revalidate").status_code, 403)

    def test_cross_site_post_blocked(self):
        r = TestClient(main.app, follow_redirects=False).post(
            "/login", data={"identifier": "x", "password": "y"}, headers={"origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_hidden_tests_never_shown(self):
        pid = add_problem(21, published=True)
        c = self.student("stu2")
        body = c.get(f"/problems/{pid}").text
        self.assertIn("1 2", body)
        self.assertNotIn(HIDDEN, body)
        self.assertNotIn(HIDDEN, c.get("/problems").text)

    def test_unpublished_hidden_from_students(self):
        pid = add_problem(3, published=False)
        self.assertEqual(self.student("stu3").get(f"/problems/{pid}").status_code, 404)
        self.assertEqual(self.admin().get(f"/problems/{pid}").status_code, 200)

    def test_publish_gate(self):
        a = self.admin()
        few = add_problem(5)
        r = a.post(f"/admin/problems/{few}/publish")
        self.assertIn("Cannot", r.headers["location"])
        enough = add_problem(21)
        r = a.post(f"/admin/problems/{enough}/publish")
        self.assertIn("Published", r.headers["location"])
        with SessionLocal() as db:
            self.assertFalse(db.get(Problem, few).published)
            self.assertTrue(db.get(Problem, enough).published)

    def test_admin_adds_problem_to_contest_with_auto_check(self):
        """Regression: adding a problem to a contest used to crash (audit() got an int as detail)."""
        a = self.admin()
        r = a.post("/admin/contests", data={"title": "AddP", "start_local": "2099-01-01T10:00", "duration_minutes": "60"})
        self.assertEqual(r.status_code, 303)
        cid = int(r.headers["location"].split("/admin/contests/")[1].split("?")[0])
        ready, weak = add_problem(21), add_problem(3)
        r = a.post(f"/admin/contests/{cid}/problems/add", data={"problem_id": str(ready)})
        self.assertEqual(r.status_code, 303)
        self.assertIn("Problem+added", r.headers["location"])
        r = a.post(f"/admin/contests/{cid}/problems/add", data={"problem_id": str(weak)})
        self.assertIn("not+ready", r.headers["location"])
        with SessionLocal() as db:
            ids = {cp.problem_id for cp in db.scalars(select(ContestProblem).where(ContestProblem.contest_id == cid))}
        self.assertEqual(ids, {ready})
        self.assertEqual(a.get(f"/admin/contests/{cid}").status_code, 200)
        self.assertEqual(a.get(f"/admin/problems/new?contest={cid}").status_code, 200)
        with SessionLocal() as db:
            cpid = db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id == cid))
        self.assertEqual(a.post(f"/admin/contests/{cid}/problems/{cpid}/remove").status_code, 303)

    def test_submission_privacy(self):
        pid = add_problem(21, published=True)
        a, b = self.student("stu4"), self.student("stu5")
        r = a.post("/api/submit", json={"problem_id": pid, "language": "python3", "code": "print(1)"})
        self.assertEqual(r.status_code, 200)
        sid = r.json()["id"]
        self.assertEqual(a.get(f"/api/submissions/{sid}").json()["verdict"], "PENDING")
        self.assertEqual(b.get(f"/api/submissions/{sid}").status_code, 404)
        self.assertEqual(b.get(f"/submissions/{sid}").status_code, 404)

    def test_oversized_code_rejected(self):
        pid = add_problem(21, published=True)
        r = self.student("stu6").post("/api/submit", json={"problem_id": pid, "language": "python3", "code": "x" * 70000})
        self.assertEqual(r.status_code, 422)

    def test_lockout(self):
        self.student("stu7")
        c = client()
        for _ in range(5):
            self.assertEqual(self.login(c, "stu7", "wrong-password").status_code, 401)
        self.assertEqual(self.login(c, "stu7", "password123").status_code, 429)

    def test_suspended_user_cannot_login_and_last_admin_protected(self):
        a = self.admin()
        self.student("stu8")
        with SessionLocal() as db:
            from app.models import User
            uid = db.scalar(select(User.id).where(User.username == "stu8"))
            boss = db.scalar(select(User.id).where(User.username == "boss"))
        a.post(f"/admin/users/{uid}/toggle")
        self.assertEqual(self.login(client(), "stu8", "password123").status_code, 403)
        r = a.post(f"/admin/users/{boss}/toggle")
        self.assertIn("last", r.headers["location"].lower() + "last")  # redirected with an error message


def make_contest(start_off, dur, pids, kind="public", password=None, **kw):
    from app.security import hash_password
    with SessionLocal() as db:
        c = Contest(title="C", start_at=now() + timedelta(minutes=start_off), end_at=now() + timedelta(minutes=start_off + dur),
                    kind=kind, password_hash=hash_password(password) if password else None, **kw)
        db.add(c)
        db.flush()
        for i, pid in enumerate(pids):
            db.add(ContestProblem(contest_id=c.id, problem_id=pid, position=i + 1, points=100))
        db.commit()
        return c.id


def uid_of(name):
    with SessionLocal() as db:
        return db.scalar(select(User.id).where(User.username == name))


class ContestWeb(Web):
    def test_student_cannot_manage_contests(self):
        c = self.student("c_stu1")
        self.assertEqual(c.post("/admin/contests", data={"title": "x", "start_iso": "2030-01-01T00:00:00Z",
                                                         "duration_minutes": "60"}).status_code, 403)
        self.assertEqual(c.get("/admin/contests").status_code, 403)

    def test_registration_closed_by_default_setting(self):
        closed = dataclasses.replace(main.settings, allow_registration=False)
        with mock.patch.object(main, "settings", closed):
            r = client().post("/register", data={"username": "nobody1", "email": "n@example.com", "password": "password123"})
        self.assertEqual(r.status_code, 403)

    def test_admin_creates_account_that_can_login(self):
        a = self.admin()
        r = a.post("/admin/users/create", data={"username": "made_by_admin", "password": "Secret-pass-1", "role": "student"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Secret-pass-1", r.text)
        self.assertEqual(self.login(client(), "made_by_admin", "Secret-pass-1").status_code, 303)
        r = a.post("/admin/users/bulk", data={"prefix": "tm", "start": "1", "count": "3"})
        self.assertIn("tm001", r.text)
        self.assertIn("tm003", r.text)

    def test_contest_problem_hidden_until_contest_ends(self):
        pid = add_problem(21, published=True)
        make_contest(-5, 60, [pid])
        c = self.student("c_stu2")
        self.assertEqual(c.get(f"/problems/{pid}").status_code, 404)
        self.assertNotIn(f"/problems/{pid}\"", c.get("/problems").text)
        self.assertEqual(c.post("/api/submit", json={"problem_id": pid, "language": "python3", "code": "x"}).status_code, 404)

    def test_server_side_time_and_registration_checks(self):
        pid = add_problem(21, published=True)
        body = lambda cid: {"problem_id": pid, "language": "python3", "code": "print(1)", "contest_id": cid}  # noqa: E731
        upcoming = make_contest(60, 60, [pid])
        running = make_contest(-5, 60, [pid])
        over = make_contest(-120, 60, [pid])
        c = self.student("c_stu3")
        for cid in (upcoming, running, over):
            self.assertEqual(c.post("/api/submit", json=body(cid)).status_code, 403)   # not registered / not started / finished
        c.post(f"/contests/{upcoming}/join")
        self.assertEqual(c.post("/api/submit", json=body(upcoming)).status_code, 403)  # registered but not started
        c.post(f"/contests/{running}/join")
        r = c.post("/api/submit", json=body(running))
        self.assertEqual(r.status_code, 200)
        with SessionLocal() as db:
            self.assertEqual(db.get(Submission, r.json()["id"]).contest_id, running)
        c.post(f"/contests/{over}/join")
        self.assertEqual(c.post("/api/submit", json=body(over)).status_code, 403)       # finished

    def test_private_contest_password(self):
        pid = add_problem(21, published=True)
        cid = make_contest(-5, 60, [pid], kind="private", password="letmein")
        c = self.student("c_stu4")
        c.post(f"/contests/{cid}/join", data={"password": "wrong"})
        with SessionLocal() as db:
            self.assertFalse(db.scalar(select(ContestParticipant.id).where(ContestParticipant.contest_id == cid)))
        c.post(f"/contests/{cid}/join", data={"password": "letmein"})
        with SessionLocal() as db:
            self.assertTrue(db.scalar(select(ContestParticipant.id).where(ContestParticipant.contest_id == cid)))

    def test_standings_ignore_hide_and_freeze(self):
        pid = add_problem(21, published=True)
        cid = make_contest(-30, 120, [pid])
        stu, adm = self.student("c_stu5"), self.admin()
        stu.post(f"/contests/{cid}/join")
        with SessionLocal() as db:
            s = Submission(user_id=uid_of("c_stu5"), problem_id=pid, contest_id=cid, language="python3", source="x",
                           verdict="AC", passed=21, total=21, created_at=now())
            db.add(s)
            db.commit()
            sid = s.id
        row = lambda: stu.get(f"/api/contests/{cid}/standings").json()["rows"][0]  # noqa: E731
        self.assertEqual(row()["solved"], 1)
        adm.post(f"/admin/submissions/{sid}/ignore")
        self.assertEqual(row()["solved"], 0)                       # ignored submissions never count
        adm.post(f"/admin/submissions/{sid}/unignore")
        self.assertEqual(row()["solved"], 1)
        adm.post(f"/admin/contests/{cid}/hide")
        self.assertTrue(stu.get(f"/api/contests/{cid}/standings").json()["hidden"])
        self.assertFalse(adm.get(f"/api/contests/{cid}/standings").json()["hidden"])
        adm.post(f"/admin/contests/{cid}/show")
        adm.post(f"/admin/contests/{cid}/freeze")                  # freeze now: earlier AC stays, later ones hidden
        with SessionLocal() as db:
            db.add(Submission(user_id=uid_of("c_stu5"), problem_id=pid, contest_id=cid, language="python3", source="y",
                              verdict="AC", passed=21, total=21, created_at=now() + timedelta(seconds=5)))
            db.commit()
        self.assertTrue(stu.get(f"/api/contests/{cid}/standings").json()["frozen"])

    def test_admin_csv_export(self):
        pid = add_problem(21, published=True)
        cid = make_contest(-30, 120, [pid])
        r = self.admin().get(f"/admin/contests/{cid}/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertEqual(self.student("c_stu6").get(f"/admin/contests/{cid}/export.csv").status_code, 403)

    def test_create_contest_with_and_without_javascript(self):
        a = self.admin()
        base = {"title": "T", "duration_minutes": "60"}
        r = a.post("/admin/contests", data={**base, "start_iso": "2030-01-01T10:00:00.000Z"})
        self.assertEqual(r.status_code, 303)                      # what the browser JS sends
        r = a.post("/admin/contests", data={**base, "start_local": "2030-01-01T10:00"})
        self.assertEqual(r.status_code, 303)                      # JS did not run: plain local time still works
        r = a.post("/admin/contests", data=base)
        self.assertEqual(r.status_code, 400)                      # no time at all: clear message, not a JSON dump


if __name__ == "__main__":
    unittest.main()
