from urllib.parse import quote
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .db import SessionLocal
from .models import AuthSession, User
from .security import hash_token
from .timeutil import aware, now


def get_db():
    with SessionLocal() as db:
        yield db


def _user_from_cookie(request: Request, db):
    tok = request.cookies.get("sid")
    if not tok:
        return None
    s = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(tok)))
    if not s or aware(s.expires_at) <= now():
        return None
    u = db.get(User, s.user_id)
    return u if u and u.is_active else None


def optional_user(request: Request, db=Depends(get_db)):
    return _user_from_cookie(request, db)


def login_required(request: Request, db=Depends(get_db)):
    u = _user_from_cookie(request, db)
    if u:
        return u
    if request.url.path.startswith(("/api", "/admin/api")):
        raise HTTPException(401, "Login required")
    raise HTTPException(303, headers={"Location": "/login?next=" + quote(request.url.path)})


def user_perms(user):
    return {p.code for p in user.role.permissions}


def require_perm(code):
    def dep(user=Depends(login_required)):
        if code not in user_perms(user):
            raise HTTPException(403, "Forbidden")
        return user
    return dep
