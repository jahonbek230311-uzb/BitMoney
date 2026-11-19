import re, secrets
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from .common import audit, render
from .deps import get_db, require_perm
from .models import IgnoredSubmission, Problem, Submission, User
from .users import USERNAME_RE, create_user, validate_new_user

router = APIRouter()
users_dep = require_perm("users.manage")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no look-alike characters
PREFIX_RE = re.compile(r"^[A-Za-z0-9_]{1,24}$")


def gen_password(n=8):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def users_page(request, user, db, created=None, error="", status=200):
    counts = dict(db.execute(select(Submission.user_id, func.count()).group_by(Submission.user_id)).all())
    return render(request, "admin_users.html", user, status, users=db.scalars(select(User).order_by(User.id)).all(),
                  counts=counts, created=created, error=error)


@router.post("/admin/users/create", response_class=HTMLResponse)
def create_one(request: Request, username: str = Form(...), password: str = Form(""),
               role: Literal["student", "admin"] = Form("student"), user=Depends(users_dep), db=Depends(get_db)):
    username = username.strip()
    if role == "admin" and password and len(password) < 12:
        return users_page(request, user, db, error="Admin passwords must be at least 12 characters.", status=400)
    pw = password or gen_password(12 if role == "admin" else 8)
    err = validate_new_user(db, username, f"{username}@local.invalid", pw)
    if err:
        return users_page(request, user, db, error=err, status=400)
    create_user(db, username, f"{username}@local.invalid", pw, role)
    audit(db, user, "user.create", username, role, request)
    db.commit()
    return users_page(request, user, db, created=[(username, pw)])


@router.post("/admin/users/bulk", response_class=HTMLResponse)
def create_bulk(request: Request, prefix: str = Form(...), start: int = Form(1), count: int = Form(...),
                user=Depends(users_dep), db=Depends(get_db)):
    prefix = prefix.strip()
    if not PREFIX_RE.match(prefix) or not 1 <= count <= 200 or not 0 <= start <= 100000:
        return users_page(request, user, db, error="Prefix: letters/digits/_ (max 24). Count: 1-200.", status=400)
    created, skipped = [], []
    for i in range(start, start + count):
        name = f"{prefix}{i:03d}"
        if not USERNAME_RE.match(name) or db.scalar(select(User.id).where(User.username == name)):
            skipped.append(name)
            continue
        pw = gen_password()
        create_user(db, name, f"{name}@local.invalid", pw, "student")
        created.append((name, pw))
    audit(db, user, "user.bulk_create", prefix, f"{len(created)} created, {len(skipped)} skipped", request)
    db.commit()
    return users_page(request, user, db, created=created,
                      error=("Skipped (already exist or invalid): " + ", ".join(skipped[:20])) if skipped else "")


@router.get("/admin/submissions", response_class=HTMLResponse)
def admin_submissions(request: Request, contest: int | None = None, user=Depends(require_perm("submissions.view_all")),
                      db=Depends(get_db)):
    q = (select(Submission, Problem.title, User.username).join(Problem, Problem.id == Submission.problem_id)
         .join(User, User.id == Submission.user_id).order_by(Submission.id.desc()).limit(300))
    if contest is not None:
        q = q.where(Submission.contest_id == contest)
    rows = [(r[0], r[1], r[2]) for r in db.execute(q).all()]
    return render(request, "submissions.html", user, rows=rows, title="All submissions" + (f" (contest {contest})" if contest else ""),
                  show_user=True, ignored=set(db.scalars(select(IgnoredSubmission.submission_id))), admin_actions=True)


def _back(next_url, msg):
    nxt = next_url if next_url.startswith("/admin/") else "/admin/submissions"
    return RedirectResponse(nxt + ("&" if "?" in nxt else "?") + "msg=" + msg.replace(" ", "+"), 303)


@router.post("/admin/submissions/{sid}/ignore")
def ignore(sid: int, request: Request, reason: str = Form(""), next: str = Form("/admin/submissions"),
           user=Depends(require_perm("submissions.view_all")), db=Depends(get_db)):
    if not db.get(Submission, sid):
        raise HTTPException(404, "Submission not found")
    if not db.get(IgnoredSubmission, sid):
        db.add(IgnoredSubmission(submission_id=sid, by_user=user.id, reason=reason.strip()[:255]))
        audit(db, user, "submission.ignore", sid, reason, request)
        db.commit()
    return _back(next, f"Submission {sid} is now ignored: it no longer counts anywhere.")


@router.post("/admin/submissions/{sid}/unignore")
def unignore(sid: int, request: Request, next: str = Form("/admin/submissions"),
             user=Depends(require_perm("submissions.view_all")), db=Depends(get_db)):
    ig = db.get(IgnoredSubmission, sid)
    if ig:
        db.delete(ig)
        audit(db, user, "submission.unignore", sid, request=request)
        db.commit()
    return _back(next, f"Submission {sid} counts again.")
