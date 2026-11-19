import logging, os, re, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, or_, select

from judge.engine import TestInput, judge
from judge.runners import DockerRunner, JudgeSystemError
from . import ratings, testgen
from .config import load_settings
from .db import SessionLocal, init_db
from .deps import get_db, login_required, optional_user, require_perm, user_perms
from .models import (AuditLog, AuthSession, ProfileRequest, Problem, ReferenceSolution, Role, Submission, TestCase,
                     TestResult, User)
from .ratelimit import RateLimiter
from .samples import GENERATOR_CONVENTION, SAMPLE_GENERATOR, SAMPLE_REFERENCE
from .security import hash_password, new_session_token, verify_password
from .timeutil import aware, now
from .users import create_user, validate_new_user
from .worker import docker_slots, requeue_stuck, tests_for, worker_loop

from datetime import timedelta

from .common import BASE, audit, render, settings, templates
from .contests import access_problem, locked_problem_ids
from .models import IgnoredSubmission

log = logging.getLogger("cpjudge")
runner = DockerRunner(settings.judge_image)
stop_event = threading.Event()
auth_limiter = RateLimiter(10, 60)
run_limiter = RateLimiter(10, 60)
DUMMY_HASH = hash_password("dummy-password-for-timing")
LANG = Literal["cpp17", "python3", "c", "java17", "javascript", "go", "rust", "ruby", "php"]


@asynccontextmanager
async def lifespan(app):
    init_db()
    requeue_stuck(SessionLocal)
    if settings.admin_email and settings.admin_password:
        with SessionLocal() as db:
            has_admin = db.scalar(select(User.id).join(Role).where(Role.name == "admin").limit(1))
            if not has_admin:
                create_user(db, "admin", settings.admin_email, settings.admin_password, "admin")
                log.warning("Admin account created from environment. Remove ADMIN_PASSWORD from env now.")
    if not os.environ.get("DISABLE_WORKER"):
        threading.Thread(target=worker_loop, args=(SessionLocal, runner, stop_event), daemon=True).start()
    yield
    stop_event.set()


app = FastAPI(title=settings.site_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


# ---------- security middleware ----------
@app.middleware("http")
async def security(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        src = request.headers.get("origin") or request.headers.get("referer")
        if not src or urlparse(src).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-cache"
    if request.url.path.startswith(("/problems", "/submissions", "/admin", "/api")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    if request.url.path.startswith(("/api", "/admin/api")):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html", {"site_name": settings.site_name, "user": None,
                                      "is_admin": False, "allow_reg": settings.allow_registration, "code": exc.status_code, "detail": exc.detail},
                                      status_code=exc.status_code)


def ip_of(request):
    return request.client.host if request.client else "?"


def safe_next(n):
    return n if n and n.startswith("/") and not n.startswith("//") else "/problems"


def start_session(db, user, resp):
    tok, h = new_session_token()
    db.add(AuthSession(token_hash=h, user_id=user.id, expires_at=now() + timedelta(hours=settings.session_hours)))
    db.commit()
    resp.set_cookie("sid", tok, httponly=True, samesite="lax", secure=settings.cookie_secure,
                    max_age=settings.session_hours * 3600)


# ---------- public / auth pages ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request, user=Depends(optional_user), db=Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(Problem).where(Problem.published.is_(True)))
    return render(request, "home.html", user, problem_count=n)


@app.get("/theme", response_class=HTMLResponse)
def theme_page(request: Request, user=Depends(optional_user)):
    return render(request, "theme.html", user)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user=Depends(optional_user)):
    return render(request, "login.html", user, error="", next=safe_next(request.query_params.get("next")))


@app.post("/login")
def login(request: Request, identifier: str = Form(...), password: str = Form(...), next: str = Form("/problems"),
          db=Depends(get_db)):
    if not auth_limiter.allow(ip_of(request)):
        return render(request, "login.html", None, 429, error="Too many attempts. Wait a minute.", next=next)
    ident = identifier.strip()
    u = db.scalar(select(User).where(or_(User.username == ident, func.lower(User.username) == ident.lower(),
                                         User.email == ident.lower())).order_by((User.username == ident).desc()).limit(1))
    if u and u.locked_until and aware(u.locked_until) > now():
        return render(request, "login.html", None, 429, error="Account temporarily locked. Try again later.", next=next)
    ok = verify_password(password, u.password_hash if u else DUMMY_HASH) and u is not None
    if not ok:
        if u:
            u.failed_logins += 1
            if u.failed_logins >= 5:
                u.locked_until, u.failed_logins = now() + timedelta(minutes=15), 0
            db.commit()
        return render(request, "login.html", None, 401, error="Invalid username or password.", next=next)
    if not u.is_active:
        return render(request, "login.html", None, 403, error="This account is suspended.", next=next)
    u.failed_logins, u.locked_until = 0, None
    audit(db, u, "login", request=request)
    resp = RedirectResponse(safe_next(next), status_code=303)
    start_session(db, u, resp)
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user=Depends(optional_user)):
    if not settings.allow_registration:
        return render(request, "register.html", user, 403, error="", closed=True)
    return render(request, "register.html", user, error="", closed=False)


@app.post("/register")
def register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...),
             db=Depends(get_db)):
    if not settings.allow_registration:
        raise HTTPException(403, "Registration is closed. Ask the administrator for an account.")
    if not auth_limiter.allow(ip_of(request)):
        return render(request, "register.html", None, 429, error="Too many attempts. Wait a minute.", closed=False)
    username, email = username.strip(), email.strip()
    err = validate_new_user(db, username, email, password)
    if err:
        return render(request, "register.html", None, 400, error=err, closed=False)
    u = create_user(db, username, email, password, "student")
    audit(db, u, "register", request=request)
    resp = RedirectResponse("/problems", status_code=303)
    start_session(db, u, resp)
    return resp


@app.post("/logout")
def logout(request: Request, db=Depends(get_db)):
    from .security import hash_token
    tok = request.cookies.get("sid")
    if tok:
        s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(tok)))
        if s:
            db.delete(s)
            db.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("sid")
    return resp


# ---------- student: problems ----------
def _status_maps(db, user):
    ign = select(IgnoredSubmission.submission_id)
    solved = set(db.scalars(select(distinct(Submission.problem_id)).where(
        Submission.user_id == user.id, Submission.verdict == "AC", Submission.id.not_in(ign))))
    tried = set(db.scalars(select(distinct(Submission.problem_id)).where(
        Submission.user_id == user.id, Submission.id.not_in(ign))))
    return solved, tried


@app.get("/problems", response_class=HTMLResponse)
def problems(request: Request, user=Depends(login_required), db=Depends(get_db)):
    qp = request.query_params
    q = select(Problem).where(Problem.published.is_(True))
    if qp.get("q"):
        q = q.where(Problem.title.ilike("%" + qp["q"].replace("%", "") + "%"))
    if qp.get("difficulty") in ("easy", "medium", "hard"):
        q = q.where(Problem.difficulty == qp["difficulty"])
    if qp.get("category"):
        q = q.where(Problem.category == qp["category"])
    if qp.get("tag"):
        q = q.where(Problem.tags.ilike("%" + qp["tag"].replace("%", "") + "%"))
    if qp.get("rating_min", "").isdigit():
        q = q.where(Problem.rating >= int(qp["rating_min"]))
    if qp.get("rating_max", "").isdigit():
        q = q.where(Problem.rating <= int(qp["rating_max"]))
    q = q.order_by(Problem.rating, Problem.id) if qp.get("sort") == "rating" else q.order_by(Problem.id)
    if "admin.access" not in user_perms(user):
        locked = locked_problem_ids(db)
        if locked:
            q = q.where(Problem.id.not_in(locked))
    solved, tried = _status_maps(db, user)
    rows = []
    for p in db.scalars(q):
        st = "solved" if p.id in solved else "attempted" if p.id in tried else "unsolved"
        if qp.get("status") in ("solved", "attempted", "unsolved") and qp["status"] != st:
            continue
        rows.append((p, st))
    cats = list(db.scalars(select(distinct(Problem.category)).where(Problem.published.is_(True), Problem.category != "")))
    return render(request, "problems.html", user, rows=rows, cats=cats, f=dict(qp))


@app.get("/problems/{pid}", response_class=HTMLResponse)
def problem_page(pid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    p = db.get(Problem, pid)
    is_admin = "admin.access" in user_perms(user)
    if not p or (not is_admin and (not p.published or p.id in locked_problem_ids(db))):
        raise HTTPException(404, "Problem not found")
    samples = db.scalars(select(TestCase).where(TestCase.problem_id == pid, TestCase.is_sample.is_(True),
                                                TestCase.validated.is_(True)).order_by(TestCase.ordinal)).all()
    return render(request, "problem.html", user, p=p, samples=samples)


class RunIn(BaseModel):
    problem_id: int
    language: LANG
    code: str = Field(max_length=65536)
    contest_id: int | None = None


@app.post("/api/run")
def api_run(body: RunIn, user=Depends(login_required), db=Depends(get_db)):
    if not run_limiter.allow(("run", user.id)):
        raise HTTPException(429, "Too many runs. Slow down.")
    p = access_problem(db, user, body)
    samples = db.scalars(select(TestCase).where(TestCase.problem_id == p.id, TestCase.is_sample.is_(True),
                                                TestCase.validated.is_(True)).order_by(TestCase.ordinal)).all()
    if not samples:
        raise HTTPException(409, "This problem has no sample tests.")
    try:
        with docker_slots:
            res = judge(runner, body.language, body.code, [TestInput(t.id, t.input_data, t.expected_output) for t in samples],
                        p.time_limit_ms / 1000.0, p.memory_limit_mb, p.checker_mode, capture=True)
    except (JudgeSystemError, OSError) as e:
        raise HTTPException(503, "Judge unavailable (is Docker running?): " + str(e)[:200])
    by_id = {t.id: t for t in samples}
    return {"verdict": res.verdict, "compile_log": res.compile_log,
            "tests": [{"input": by_id[t.test_id].input_data, "expected": by_id[t.test_id].expected_output,
                       "output": t.output, "stderr": t.stderr, "verdict": t.verdict, "time_ms": t.time_ms,
                       "memory_kb": t.memory_kb, "message": t.message} for t in res.tests]}


class SubmitIn(RunIn):
    pass


@app.post("/api/submit")
def api_submit(body: SubmitIn, request: Request, user=Depends(login_required), db=Depends(get_db)):
    p = access_problem(db, user, body)
    last = db.scalar(select(Submission.created_at).where(Submission.user_id == user.id)
                     .order_by(Submission.id.desc()).limit(1))
    if last and (now() - aware(last)).total_seconds() < 3:
        raise HTTPException(429, "Wait a few seconds between submissions.")
    s = Submission(user_id=user.id, problem_id=p.id, contest_id=body.contest_id, language=body.language,
                   source=body.code, verdict="PENDING")
    db.add(s)
    db.commit()
    return {"id": s.id}


@app.get("/api/submissions/{sid}")
def api_submission(sid: int, user=Depends(login_required), db=Depends(get_db)):
    s = db.get(Submission, sid)
    if not s or (s.user_id != user.id and "submissions.view_all" not in user_perms(user)):
        raise HTTPException(404, "Not found")
    return {"id": s.id, "verdict": s.verdict, "passed": s.passed, "total": s.total, "time_ms": s.time_ms,
            "memory_kb": s.memory_kb, "compile_log": s.compile_log if s.verdict in ("CE", "SE") else ""}


@app.get("/submissions", response_class=HTMLResponse)
def my_submissions(request: Request, user=Depends(login_required), db=Depends(get_db)):
    rows = db.execute(select(Submission, Problem.title).join(Problem, Problem.id == Submission.problem_id)
                      .where(Submission.user_id == user.id).order_by(Submission.id.desc()).limit(200)).all()
    return render(request, "submissions.html", user, rows=rows, title="My submissions", show_user=False,
                  ignored=set(db.scalars(select(IgnoredSubmission.submission_id))), admin_actions=False)


@app.get("/submissions/{sid}", response_class=HTMLResponse)
def submission_page(sid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    s = db.get(Submission, sid)
    if not s or (s.user_id != user.id and "submissions.view_all" not in user_perms(user)):
        raise HTTPException(404, "Submission not found")
    p = db.get(Problem, s.problem_id)
    results = db.execute(select(TestResult, TestCase.ordinal).join(TestCase, TestCase.id == TestResult.test_case_id)
                         .where(TestResult.submission_id == s.id).order_by(TestCase.ordinal)).all()
    return render(request, "submission.html", user, s=s, p=p, results=results, owner=db.get(User, s.user_id))


# ---------- admin ----------
admin_dep = require_perm("admin.access")


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    c = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w))  # noqa: E731
    stats = {"Users": c(User), "Problems": c(Problem), "Published": c(Problem, Problem.published.is_(True)),
             "Submissions": c(Submission), "Pending": c(Submission, Submission.verdict.in_(("PENDING", "JUDGING")))}
    waiting = c(ProfileRequest, ProfileRequest.status == "pending")
    return render(request, "admin_home.html", user, stats=stats, waiting=waiting)


@app.get("/admin/problems", response_class=HTMLResponse)
def admin_problems(request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    rows = [(p, testgen.valid_count(db, p.id)) for p in db.scalars(select(Problem).order_by(Problem.id.desc()))]
    return render(request, "admin_problems.html", user, rows=rows, min_tests=testgen.MIN_VALID_TESTS)


FIELDS = ("title", "statement", "input_format", "output_format", "constraints", "difficulty", "rating", "category", "tags",
          "time_limit_ms", "memory_limit_mb", "checker_mode")


def _form_values(title, statement, input_format, output_format, constraints, rating, category, tags,
                 time_limit_ms, memory_limit_mb, checker_mode):
    auto_title = next((line.strip() for line in statement.splitlines() if line.strip()), "Untitled problem")[:80]
    return dict(title=(title.strip()[:200] or auto_title), statement=statement, input_format=input_format, output_format=output_format,
                constraints=constraints, rating=rating, difficulty=ratings.difficulty_for(rating),
                category=category.strip()[:64], tags=tags.strip()[:255],
                time_limit_ms=time_limit_ms, memory_limit_mb=memory_limit_mb, checker_mode=checker_mode)


def _validate_problem(v):
    if not v["statement"].strip():
        return "Problem statement is required."
    if not ratings.valid(v["rating"]):
        return f"Rating must be between {ratings.MIN_RATING} and {ratings.MAX_RATING}."
    if not 100 <= v["time_limit_ms"] <= 20000:
        return "Time limit must be 100-20000 ms."
    if not 16 <= v["memory_limit_mb"] <= 1024:
        return "Memory limit must be 16-1024 MB."
    return None


def problem_form(title: str = Form(""), statement: str = Form(...), input_format: str = Form(""),
                 output_format: str = Form(""), constraints: str = Form(""),
                 rating: int = Form(800), category: str = Form(""),
                 tags: str = Form(""), time_limit_ms: int = Form(1000), memory_limit_mb: int = Form(256),
                 checker_mode: Literal["tokens", "lines", "exact", "float"] = Form("tokens")):
    return _form_values(title, statement, input_format, output_format, constraints, rating, category, tags,
                        time_limit_ms, memory_limit_mb, checker_mode)


@app.get("/admin/problems/new", response_class=HTMLResponse)
def admin_problem_new(request: Request, user=Depends(admin_dep)):
    cid = request.query_params.get("contest", "")
    return render(request, "admin_problem_new.html", user, error="", rating_choices=ratings.CHOICES,
                  contest_id=cid if cid.isdigit() else "")


@app.post("/admin/problems")
def admin_problem_create(request: Request, v=Depends(problem_form), contest: str = Form(""),
                         user=Depends(admin_dep), db=Depends(get_db)):
    contest = contest.strip() if contest.strip().isdigit() else ""
    err = _validate_problem(v)
    if err:
        return render(request, "admin_problem_new.html", user, 400, error=err, rating_choices=ratings.CHOICES,
                      contest_id=contest)
    p = Problem(created_by=user.id, **v)
    db.add(p)
    audit(db, user, "problem.create", v["title"], request=request)
    db.commit()
    extra = (f"&contest={contest}" if contest else "")
    return RedirectResponse(f"/admin/problems/{p.id}/edit?msg=Problem+created.+Add+reference+and+manual+tests.{extra}", 303)


def _get_problem(db, pid):
    p = db.get(Problem, pid)
    if not p:
        raise HTTPException(404, "Problem not found")
    return p


@app.get("/admin/problems/{pid}/edit", response_class=HTMLResponse)
def admin_problem_edit(pid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    tests = db.scalars(select(TestCase).where(TestCase.problem_id == pid).order_by(TestCase.ordinal)).all()
    cid = request.query_params.get("contest", "")
    issues, warns = testgen.readiness(db, p)
    return render(request, "admin_problem_edit.html", user, p=p, tests=tests, ref=testgen.get_reference(db, p),
                  contest_id=int(cid) if cid.isdigit() else None, issues=issues, warns=warns,
                  valid=testgen.valid_count(db, pid), min_tests=testgen.MIN_VALID_TESTS, error="",
                  sample_ref=SAMPLE_REFERENCE, sample_gen=SAMPLE_GENERATOR, convention=GENERATOR_CONVENTION,
                  rating_choices=ratings.CHOICES)


@app.post("/admin/problems/{pid}")
def admin_problem_update(pid: int, request: Request, v=Depends(problem_form), user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    err = _validate_problem(v)
    if err:
        return RedirectResponse(f"/admin/problems/{pid}/edit?msg=" + err.replace(" ", "+"), 303)
    for k, val in v.items():
        setattr(p, k, val)
    audit(db, user, "problem.update", pid, request=request)
    db.commit()
    return RedirectResponse(f"/admin/problems/{pid}/edit?msg=Saved.", 303)


@app.post("/admin/problems/{pid}/publish")
def admin_publish(pid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    issues, _ = testgen.readiness(db, p)
    if issues:
        return RedirectResponse(f"/admin/problems/{pid}/edit?msg=" + quote_plus("Cannot publish: " + "; ".join(issues) + "."), 303)
    p.published = True
    audit(db, user, "problem.publish", pid, request=request)
    db.commit()
    return RedirectResponse(f"/admin/problems/{pid}/edit?msg=Published.", 303)


@app.post("/admin/problems/{pid}/unpublish")
def admin_unpublish(pid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    p.published = False
    audit(db, user, "problem.unpublish", pid, request=request)
    db.commit()
    return RedirectResponse(f"/admin/problems/{pid}/edit?msg=Unpublished.", 303)


@app.post("/admin/problems/{pid}/delete")
def admin_delete(pid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    audit(db, user, "problem.delete", pid, p.title, request)
    db.delete(p)
    db.commit()
    return RedirectResponse("/admin/problems?msg=Deleted.", 303)


@app.post("/admin/problems/{pid}/duplicate")
def admin_duplicate(pid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    n = Problem(created_by=user.id, published=False, **{k: getattr(p, k) for k in FIELDS})
    n.title = (p.title + " (copy)")[:200]
    db.add(n)
    db.flush()
    for t in db.scalars(select(TestCase).where(TestCase.problem_id == pid)):
        db.add(TestCase(problem_id=n.id, ordinal=t.ordinal, input_data=t.input_data, expected_output=t.expected_output,
                        is_sample=t.is_sample, kind=t.kind, source=t.source, input_hash=t.input_hash, validated=t.validated))
    r = testgen.get_reference(db, p)
    if r:
        db.add(ReferenceSolution(problem_id=n.id, language=r.language, source=r.source))
    audit(db, user, "problem.duplicate", pid, request=request)
    db.commit()
    return RedirectResponse(f"/admin/problems/{n.id}/edit?msg=Duplicated+(unpublished).", 303)


# admin JSON API (sandboxed work runs here, in the threadpool)
class RefIn(BaseModel):
    language: LANG
    source: str = Field(min_length=1, max_length=65536)


class TestIn(BaseModel):
    input: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    expected: str = Field("", max_length=2 * 1024 * 1024)
    is_sample: bool = False


@app.post("/admin/api/problems/{pid}/reference")
def api_save_reference(pid: int, payload: RefIn, request: Request,
                       user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    # Allow only languages installed in the isolated judge image.
    if payload.language not in ("cpp17", "python3", "c", "java17", "javascript", "go", "rust", "ruby", "php"):
        raise HTTPException(422, "Unsupported reference language")
    src = payload.source.strip()
    if not src:
        raise HTTPException(422, "Reference source is required")
    db.add(ReferenceSolution(problem_id=p.id, language=payload.language, source=src))
    audit(db, user, "reference.save", f"problem={pid}; language={payload.language}", request=request)
    db.commit()
    return {"ok": True, "message": "Reference solution saved. You can now save manual tests."}


@app.post("/admin/api/problems/{pid}/tests")
def api_add_manual_test(pid: int, payload: TestIn, request: Request,
                        user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    result = testgen.add_manual(db, p, payload.input, payload.expected, payload.is_sample, runner)
    if result.get("ok"):
        audit(db, user, "test.manual_add", f"problem={pid}; sample={payload.is_sample}", request=request)
    return result


@app.post("/admin/api/problems/{pid}/revalidate")
def api_revalidate(pid: int, user=Depends(admin_dep), db=Depends(get_db)):
    p = _get_problem(db, pid)
    return testgen.revalidate(db, p, runner)


@app.post("/admin/api/tests/{tid}/delete")
def api_delete_test(tid: int, request: Request, user=Depends(admin_dep), db=Depends(get_db)):
    t = db.get(TestCase, tid)
    if not t:
        raise HTTPException(404, "Test not found")
    pid = t.problem_id
    db.delete(t)
    audit(db, user, "test.delete", tid, request=request)
    db.commit()
    p = db.get(Problem, pid)
    n = testgen.valid_count(db, pid)
    if p.published and n < testgen.MIN_VALID_TESTS:  # keep the publish invariant
        p.published = False
        db.commit()
    return {"ok": True, "total_valid": n, "unpublished": not p.published}


@app.get("/admin/api/tests/{tid}")
def api_test_detail(tid: int, user=Depends(admin_dep), db=Depends(get_db)):
    t = db.get(TestCase, tid)
    if not t:
        raise HTTPException(404, "Test not found")
    return {"input": t.input_data[:20000], "expected": t.expected_output[:20000],
            "truncated": len(t.input_data) > 20000 or len(t.expected_output) > 20000}


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user=Depends(require_perm("users.manage")), db=Depends(get_db)):
    counts = dict(db.execute(select(Submission.user_id, func.count()).group_by(Submission.user_id)).all())
    users = db.scalars(select(User).order_by(User.id)).all()
    return render(request, "admin_users.html", user, users=users, counts=counts)


def _last_admin_guard(db, target, new_role=None, deactivate=False):
    if target.role.name != "admin":
        return None
    if not (deactivate or (new_role and new_role != "admin")):
        return None
    others = db.scalar(select(func.count()).select_from(User).join(Role).where(
        Role.name == "admin", User.is_active.is_(True), User.id != target.id))
    return "Cannot remove or suspend the last active admin." if not others else None


@app.post("/admin/users/{uid}/toggle")
def admin_user_toggle(uid: int, request: Request, user=Depends(require_perm("users.manage")), db=Depends(get_db)):
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404, "User not found")
    if t.is_active:
        err = _last_admin_guard(db, t, deactivate=True) or ("You cannot suspend yourself." if t.id == user.id else None)
        if err:
            return RedirectResponse("/admin/users?msg=" + err.replace(" ", "+"), 303)
    t.is_active = not t.is_active
    if not t.is_active:
        for s in db.scalars(select(AuthSession).where(AuthSession.user_id == t.id)):
            db.delete(s)
    audit(db, user, "user.suspend" if not t.is_active else "user.reactivate", uid, request=request)
    db.commit()
    return RedirectResponse("/admin/users?msg=Updated.", 303)


@app.post("/admin/users/{uid}/role")
def admin_user_role(uid: int, request: Request, role: Literal["admin", "student"] = Form(...),
                    user=Depends(require_perm("users.manage")), db=Depends(get_db)):
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404, "User not found")
    err = _last_admin_guard(db, t, new_role=role)
    if err:
        return RedirectResponse("/admin/users?msg=" + err.replace(" ", "+"), 303)
    t.role_id = db.scalar(select(Role.id).where(Role.name == role))
    audit(db, user, "user.role", uid, role, request)
    db.commit()
    return RedirectResponse("/admin/users?msg=Role+updated.", 303)


@app.post("/admin/users/{uid}/password")
def admin_user_password(uid: int, request: Request, password: str = Form(...),
                        user=Depends(require_perm("users.manage")), db=Depends(get_db)):
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404, "User not found")
    if len(password) < 8:
        return RedirectResponse("/admin/users?msg=Password+must+be+at+least+8+characters.", 303)
    t.password_hash = hash_password(password)
    t.failed_logins, t.locked_until = 0, None
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == t.id)):
        db.delete(s)
    audit(db, user, "user.password_reset", uid, request=request)
    db.commit()
    return RedirectResponse("/admin/users?msg=Password+reset.+All+sessions+of+that+user+were+ended.", 303)


from .admin_extra import router as admin_extra_router  # noqa: E402
from .contest_routes import router as contest_router  # noqa: E402

from .global_standings import router as global_router  # noqa: E402
from .profile_routes import router as profile_router  # noqa: E402

app.include_router(contest_router)
app.include_router(admin_extra_router)
app.include_router(global_router)
app.include_router(profile_router)
