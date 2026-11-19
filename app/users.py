import re
from sqlalchemy import select
from .models import Role, User
from .security import hash_password

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_new_user(db, username, email, password):
    if not USERNAME_RE.match(username):
        return "Username: 3-32 characters, letters, digits and underscore only."
    if not EMAIL_RE.match(email) or len(email) > 255:
        return "Invalid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if db.scalar(select(User).where(User.username == username)):
        return "Username already taken."
    if db.scalar(select(User).where(User.email == email.lower())):
        return "Email already registered."
    return None


def create_user(db, username, email, password, role_name="student"):
    role = db.scalar(select(Role).where(Role.name == role_name))
    u = User(username=username, email=email.lower(), password_hash=hash_password(password), role_id=role.id)
    db.add(u)
    db.commit()
    return u
