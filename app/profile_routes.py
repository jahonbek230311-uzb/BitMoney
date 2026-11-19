"""User profiles. A student's picture, description, email and password changes are REQUESTS: they wait for an
administrator to accept them (Admin > Profile requests). Admins' own changes apply immediately."""
import os, re, secrets
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import distinct, func, select

from .common import audit, render
from .deps import get_db, login_required, require_perm, user_perms
from .models import AuthSession, IgnoredSubmission, Problem, ProfileRequest, Submission, User
from .ratelimit import RateLimiter
from .security import hash_password, verify_password
from .timeutil import now
from .users import EMAIL_RE

router = APIRouter()
users_dep = require_perm("users.manage")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads")) / "avatars"
AVATAR_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
MAX_AVATAR = 1024 * 1024
DESC_MAX = 500
req_limiter = RateLimiter(10, 60)


def go(url, msg):
    return RedirectResponse(url + "?msg=" + quote_plus(msg), 303)


# ---------- avatar files ----------
def sniff(data: bytes):
    """Image type from the file's own bytes (the client's file name / content type are never trusted). No SVG."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def save_avatar(upload: UploadFile) -> str:
    data = upload.file.read(MAX_AVATAR + 1)
    if len(data) > MAX_AVATAR:
        raise ValueError("Picture must be at most 1 MB.")
    ext = sniff(data)
    if not ext:
        raise ValueError("Picture must be a PNG, JPEG, WebP or GIF image.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(16) + "." + ext
    (UPLOAD_DIR / name).write_bytes(data)
    return name


def delete_file(name):
    if name and AVATAR_RE.match(name):
        try:
            (UPLOAD_DIR / name).unlink()
        except OSError:
            pass


@router.get("/avatar/{name}")
def avatar_file(name: str, user=Depends(login_required), db=Depends(get_db)):
    path = UPLOAD_DIR / name
    if not AVATAR_RE.match(name) or not path.is_file():
        raise HTTPException(404, "Not found")
    if db.scalar(select(User.id).where(User.avatar == name).limit(1)) is None and "admin.access" not in user_perms(user):
        mine = db.scalar(select(ProfileRequest.id).where(ProfileRequest.user_id == user.id, ProfileRequest.kind == "avatar",
                                                         ProfileRequest.value == name).limit(1))
        if mine is None:   # a picture that is still waiting for approval is visible to its owner and to admins only
            raise HTTPException(404, "Not found")
    return FileResponse(path, media_type=MEDIA[name.rsplit(".", 1)[1]], headers={"Cache-Control": "private, max-age=3600"})


# ---------- applying a change ----------
def apply_change(db, target, kind, value, end_sessions=True):
    """Returns an error string, or None when the change was applied."""
    if kind == "description":
        target.description = value
    elif kind == "email":
        if db.scalar(select(User.id).where(User.email == value, User.id != target.id)):
            return "That email is now used by another account."
        target.email = value
    elif kind == "password":
        target.password_hash = value
        target.failed_logins, target.locked_until = 0, None
        if end_sessions:
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == target.id)):
                db.delete(s)
    elif kind == "avatar":
        old = target.avatar
        target.avatar = value
        if old and old != value:
            delete_file(old)
    else:
        return "Unknown change."
    return None


# ---------- pages ----------
def stats(db, uid):
    ign = select(IgnoredSubmission.submission_id)
    base = (Submission.user_id == uid, Submission.id.not_in(ign))
    solved = list(db.scalars(select(distinct(Submission.problem_id)).where(*base, Submission.verdict == "AC")))
    tried = db.scalar(select(func.count(distinct(Submission.problem_id))).where(*base)) or 0
    total = db.scalar(select(func.count()).select_from(Submission).where(*base)) or 0
    ac = db.scalar(select(func.count()).select_from(Submission).where(*base, Submission.verdict == "AC")) or 0
    ids = solved or [0]
    by_diff = dict(db.execute(select(Problem.difficulty, func.count()).where(Problem.id.in_(ids))
                              .group_by(Problem.difficulty)).all())
    points = db.scalar(select(func.coalesce(func.sum(Problem.rating), 0)).where(Problem.id.in_(ids))) or 0
    return dict(solved=len(solved), tried=tried, total=total, ac=ac, by_diff=by_diff, points=points)


@router.get("/profile", response_class=HTMLResponse)
def my_profile(request: Request, user=Depends(login_required), db=Depends(get_db)):
    reqs = db.scalars(select(ProfileRequest).where(ProfileRequest.user_id == user.id)
                      .order_by(ProfileRequest.id.desc()).limit(15)).all()
    pending = {r.kind: r for r in reqs if r.status == "pending"}
    return render(request, "profile.html", user, target=user, own=True, reqs=reqs, pending=pending, **stats(db, user.id))


@router.get("/users/{username}", response_class=HTMLResponse)
def public_profile(username: str, request: Request, user=Depends(login_required), db=Depends(get_db)):
    t = db.scalar(select(User).where(User.username == username))
    if not t or not t.is_active:
        raise HTTPException(404, "User not found")
    if t.id == user.id:
        return RedirectResponse("/profile", 303)
    return render(request, "profile.html", user, target=t, own=False, reqs=[], pending={}, **stats(db, t.id))


@router.post("/profile/request")
def profile_request(request: Request, description: str | None = Form(None), email: str = Form(""),
                    current_password: str = Form(""), new_password: str = Form(""),
                    avatar: UploadFile | None = File(None), user=Depends(login_required), db=Depends(get_db)):
    if not req_limiter.allow(("profile", user.id)):
        raise HTTPException(429, "Too many requests. Wait a minute.")
    instant = "admin.access" in user_perms(user)
    errors, changes = [], []

    if description is not None and description.strip() != (user.description or ""):
        if len(description.strip()) > DESC_MAX:
            errors.append(f"Description is limited to {DESC_MAX} characters.")
        else:
            changes.append(("description", description.strip()))
    em = email.strip().lower()
    if em and em != user.email:
        if not EMAIL_RE.match(em) or len(em) > 255:
            errors.append("Invalid email address.")
        elif db.scalar(select(User.id).where(User.email == em, User.id != user.id)):
            errors.append("That email is already used by another account.")
        else:
            changes.append(("email", em))
    if new_password:
        if len(new_password) < 8:
            errors.append("The new password must be at least 8 characters.")
        elif not verify_password(current_password, user.password_hash):
            errors.append("Your current password is wrong.")
        else:
            changes.append(("password", hash_password(new_password)))
    new_file = None
    if avatar is not None and avatar.filename:
        try:
            new_file = save_avatar(avatar)
            changes.append(("avatar", new_file))
        except ValueError as e:
            errors.append(str(e))
    if errors:
        delete_file(new_file)
        return go("/profile", " ".join(errors))
    if not changes:
        return go("/profile", "Nothing to change.")

    for kind, value in changes:
        if instant:   # an administrator does not need anyone's approval
            apply_change(db, user, kind, value, end_sessions=False)
            continue
        for old in db.scalars(select(ProfileRequest).where(ProfileRequest.user_id == user.id, ProfileRequest.kind == kind,
                                                           ProfileRequest.status == "pending")):
            if kind == "avatar":
                delete_file(old.value)
            db.delete(old)
        db.add(ProfileRequest(user_id=user.id, kind=kind, value=value))
    audit(db, user, "profile.change" if instant else "profile.request", user.id, ",".join(k for k, _ in changes), request)
    db.commit()
    if instant:
        return go("/profile", "Saved.")
    return go("/profile", "Sent to the administrator. It takes effect when they accept it."
              + (" After a password change is accepted you must log in again." if any(k == "password" for k, _ in changes) else ""))


# ---------- admin: review ----------
@router.get("/admin/profile-requests", response_class=HTMLResponse)
def admin_requests(request: Request, user=Depends(users_dep), db=Depends(get_db)):
    rows = db.execute(select(ProfileRequest, User.username).join(User, User.id == ProfileRequest.user_id)
                      .order_by(ProfileRequest.id.desc()).limit(150)).all()
    return render(request, "admin_profile_requests.html", user, pending=[r for r in rows if r[0].status == "pending"],
                  done=[r for r in rows if r[0].status != "pending"][:40])


def _decide(rid, request, user, db, accept, note=""):
    r = db.get(ProfileRequest, rid)
    if not r or r.status != "pending":
        return go("/admin/profile-requests", "That request was not found or is already handled.")
    target = db.get(User, r.user_id)
    err = None
    if accept:
        err = apply_change(db, target, r.kind, r.value) if target else "The user no longer exists."
    if accept and not err:
        r.status, r.note = "accepted", ""
    else:
        r.status, r.note = "rejected", (err or note)[:255]
        if r.kind == "avatar":
            delete_file(r.value)
    if r.kind == "password":
        r.value = ""   # never keep the hash once the request is closed
    r.decided_at, r.decided_by = now(), user.id
    audit(db, user, "profile." + r.status, rid, f"{r.kind} user={r.user_id}", request)
    db.commit()
    return go("/admin/profile-requests", "Accepted and applied." if r.status == "accepted" else "Rejected." + (f" ({err})" if err else ""))


@router.post("/admin/profile-requests/{rid}/accept")
def accept_request(rid: int, request: Request, user=Depends(users_dep), db=Depends(get_db)):
    return _decide(rid, request, user, db, True)


@router.post("/admin/profile-requests/{rid}/reject")
def reject_request(rid: int, request: Request, note: str = Form(""), user=Depends(users_dep), db=Depends(get_db)):
    return _decide(rid, request, user, db, False, note.strip())
