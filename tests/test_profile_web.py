"""Web tests for ratings, the overall standings, profile change requests and pasted contest registration.
Run on their own:  python -m unittest tests.test_profile_web   (needs fastapi + sqlalchemy; no Docker)."""
import os, tempfile, unittest
from datetime import timedelta

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(_tmp, "p.db").replace("\\", "/"))
os.environ.setdefault("DISABLE_WORKER", "1")
os.environ.setdefault("ALLOW_REGISTRATION", "1")
os.environ.setdefault("UPLOAD_DIR", os.path.join(_tmp, "uploads"))
os.environ.pop("APP_ENV", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from app import main  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Contest, ContestParticipant, Problem, ProfileRequest, Submission, User  # noqa: E402
from app.timeutil import now  # noqa: E402
from app.users import create_user  # noqa: E402

H = {"origin": "http://testserver"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def client():
    return TestClient(main.app, headers=H, follow_redirects=False)


def user_row(name):
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username == name))


def requests_of(name, kind=None):
    with SessionLocal() as db:
        q = select(ProfileRequest).join(User, User.id == ProfileRequest.user_id).where(User.username == name)
        if kind:
            q = q.where(ProfileRequest.kind == kind)
        return list(db.scalars(q.order_by(ProfileRequest.id)))


class ProfileWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(main.app)
        cls.ctx.__enter__()
        with SessionLocal() as db:
            if not db.scalar(select(User.id).where(User.username == "pf_boss")):
                create_user(db, "pf_boss", "pf_boss@example.com", "a-long-admin-pass", "admin")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        main.auth_limiter.hits.clear()

    def student(self, name):
        c = client()
        r = c.post("/register", data={"username": name, "email": name + "@example.com", "password": "password123"})
        self.assertEqual(r.status_code, 303)
        return c

    def admin(self):
        c = client()
        r = c.post("/login", data={"identifier": "pf_boss", "password": "a-long-admin-pass", "next": "/problems"})
        self.assertEqual(r.status_code, 303)
        return c

    # ---- ratings ----
    def test_admin_sets_rating_and_difficulty_follows(self):
        a = self.admin()
        for rating, diff in ((800, "easy"), (1200, "medium"), (2000, "hard"), (3500, "hard")):
            r = a.post("/admin/problems", data={"title": f"R{rating}", "statement": "s", "rating": str(rating)})
            self.assertEqual(r.status_code, 303)
            with SessionLocal() as db:
                p = db.scalar(select(Problem).where(Problem.title == f"R{rating}"))
                self.assertEqual((p.rating, p.difficulty), (rating, diff))
        r = a.post("/admin/problems", data={"title": "bad", "statement": "s", "rating": "100"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.student("pf_s0").post("/admin/problems", data={"title": "x", "statement": "s"}).status_code, 403)

    def test_problem_list_rating_filter(self):
        with SessionLocal() as db:
            db.add(Problem(title="LowRatedZZ", statement="s", difficulty="easy", rating=800, published=True))
            db.add(Problem(title="HighRatedZZ", statement="s", difficulty="hard", rating=2000, published=True))
            db.commit()
        c = self.student("pf_s1")
        body = c.get("/problems?rating_min=1500").text
        self.assertIn("HighRatedZZ", body)
        self.assertNotIn("LowRatedZZ", body)
        body = c.get("/problems?rating_max=1000&sort=rating").text
        self.assertIn("LowRatedZZ", body)
        self.assertNotIn("HighRatedZZ", body)

    # ---- overall standings ----
    def test_overall_standings(self):
        with SessionLocal() as db:
            p = Problem(title="StandZZ", statement="s", difficulty="easy", rating=1000, published=True)
            db.add(p)
            db.flush()
            pid = p.id
        c = self.student("pf_s2")
        uid = user_row("pf_s2").id
        with SessionLocal() as db:
            db.add(Submission(user_id=uid, problem_id=pid, language="python3", source="x", verdict="AC", passed=1, total=1))
            db.commit()
        r = c.get("/standings")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/users/pf_s2", r.text)
        self.assertIn("<h2>Overall standings</h2>", r.text)
        part = c.get("/standings?partial=1")
        self.assertEqual(part.status_code, 200)
        self.assertNotIn("<html", part.text)
        self.assertEqual(client().get("/standings").status_code, 303)    # login required

    # ---- profile requests ----
    def test_changes_wait_for_admin_then_apply(self):
        c = self.student("pf_s3")
        r = c.post("/profile/request", data={"description": "I like graphs", "email": "new_pf_s3@example.com"})
        self.assertEqual(r.status_code, 303)
        u = user_row("pf_s3")
        self.assertEqual((u.description, u.email), ("", "pf_s3@example.com"))     # nothing applied yet
        self.assertEqual({q.kind for q in requests_of("pf_s3")}, {"description", "email"})
        self.assertIn("waiting for approval", c.get("/profile").text)
        a = self.admin()
        self.assertIn("pf_s3", a.get("/admin/profile-requests").text)
        for q in requests_of("pf_s3"):
            self.assertEqual(a.post(f"/admin/profile-requests/{q.id}/accept").status_code, 303)
        u = user_row("pf_s3")
        self.assertEqual((u.description, u.email), ("I like graphs", "new_pf_s3@example.com"))
        self.assertTrue(all(q.status == "accepted" for q in requests_of("pf_s3")))

    def test_rejected_change_is_not_applied(self):
        c = self.student("pf_s4")
        c.post("/profile/request", data={"description": "spam"})
        q = requests_of("pf_s4", "description")[0]
        self.assertEqual(self.admin().post(f"/admin/profile-requests/{q.id}/reject", data={"note": "no"}).status_code, 303)
        self.assertEqual(user_row("pf_s4").description, "")
        self.assertEqual(requests_of("pf_s4", "description")[0].status, "rejected")

    def test_password_change_needs_current_password_and_approval(self):
        c = self.student("pf_s5")
        r = c.post("/profile/request", data={"current_password": "wrong-one", "new_password": "brand-new-pass"})
        self.assertIn("wrong", r.headers["location"])
        self.assertEqual(requests_of("pf_s5"), [])
        r = c.post("/profile/request", data={"current_password": "password123", "new_password": "brand-new-pass"})
        self.assertEqual(r.status_code, 303)
        q = requests_of("pf_s5", "password")[0]
        self.assertNotIn("brand-new-pass", q.value)                                # only a hash is stored
        login = lambda pw: client().post("/login", data={"identifier": "pf_s5", "password": pw, "next": "/problems"})  # noqa: E731
        self.assertEqual(login("password123").status_code, 303)                    # old password still valid until accepted
        self.admin().post(f"/admin/profile-requests/{q.id}/accept")
        self.assertEqual(login("password123").status_code, 401)
        self.assertEqual(login("brand-new-pass").status_code, 303)
        self.assertEqual(requests_of("pf_s5", "password")[0].value, "")

    def test_avatar_validation_visibility_and_approval(self):
        c, other = self.student("pf_s6"), self.student("pf_s7")
        bad = c.post("/profile/request", files={"avatar": ("x.png", b"definitely not an image", "image/png")})
        self.assertIn("must", bad.headers["location"])
        big = c.post("/profile/request", files={"avatar": ("x.png", PNG + b"0" * (1024 * 1024), "image/png")})
        self.assertIn("1+MB", big.headers["location"])
        self.assertEqual(requests_of("pf_s6", "avatar"), [])
        self.assertEqual(c.post("/profile/request", files={"avatar": ("me.png", PNG, "image/png")}).status_code, 303)
        q = requests_of("pf_s6", "avatar")[0]
        url = f"/avatar/{q.value}"
        self.assertIsNone(user_row("pf_s6").avatar)
        self.assertEqual(c.get(url).status_code, 200)                              # owner sees the pending picture
        self.assertEqual(other.get(url).status_code, 404)                          # nobody else does
        a = self.admin()
        self.assertEqual(a.get(url).status_code, 200)                              # admin can review it
        a.post(f"/admin/profile-requests/{q.id}/accept")
        self.assertEqual(user_row("pf_s6").avatar, q.value)
        self.assertEqual(other.get(url).status_code, 200)                          # approved: visible to everyone
        self.assertEqual(c.get("/avatar/../../etc/passwd").status_code, 404)

    def test_admin_own_changes_apply_immediately(self):
        a = self.admin()
        r = a.post("/profile/request", data={"description": "the boss"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(user_row("pf_boss").description, "the boss")
        self.assertEqual(requests_of("pf_boss"), [])

    def test_students_cannot_review_requests(self):
        c = self.student("pf_s8")
        c.post("/profile/request", data={"description": "x"})
        q = requests_of("pf_s8")[0]
        self.assertEqual(c.get("/admin/profile-requests").status_code, 403)
        self.assertEqual(c.post(f"/admin/profile-requests/{q.id}/accept").status_code, 403)
        self.assertEqual(user_row("pf_s8").description, "")

    def test_public_profile_hides_email(self):
        c = self.student("pf_s9")
        self.student("pf_s10")
        body = c.get("/users/pf_s10").text
        self.assertIn("pf_s10", body)
        self.assertNotIn("pf_s10@example.com", body)
        self.assertEqual(c.get("/users/pf_s9").status_code, 303)                   # own page is /profile

    # ---- contest: paste usernames ----
    def test_admin_registers_participants_by_pasted_usernames(self):
        self.student("pf_s11")
        with SessionLocal() as db:
            c = Contest(title="PasteC", start_at=now() + timedelta(minutes=30), end_at=now() + timedelta(minutes=150))
            db.add(c)
            db.commit()
            cid = c.id
        r = self.admin().post(f"/admin/contests/{cid}/participants/add", data={"usernames": "pf_s11,\nno_such_user"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("Unknown", r.headers["location"])
        with SessionLocal() as db:
            ids = set(db.scalars(select(ContestParticipant.user_id).where(ContestParticipant.contest_id == cid)))
        self.assertEqual(ids, {user_row("pf_s11").id})


if __name__ == "__main__":
    unittest.main()
