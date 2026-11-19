"""python -m app.cli init | create-admin | reset-admin | has-admin | seed-sample"""
import argparse, getpass, sys
from sqlalchemy import func, select
from judge.runners import DockerRunner
from . import testgen
from .config import load_settings
from .db import SessionLocal, init_db
from .models import Problem, ReferenceSolution, Role, User
from .samples import SAMPLE_GENERATOR, SAMPLE_REFERENCE
from .security import hash_password
from .users import create_user, validate_new_user


def create_admin():
    init_db()
    s = load_settings()
    with SessionLocal() as db:
        username = input("Admin username [Jahonbek]: ").strip() or "Jahonbek"
        email = (s.admin_email or input("Admin email [jahonbek230311@gmail.com]: ").strip() or "jahonbek230311@gmail.com").strip()
        pw = s.admin_password or getpass.getpass("Admin password (min 12 chars, not echoed): ")
        if len(pw) < 12:
            sys.exit("Password must be at least 12 characters.")
        if pw != (s.admin_password or getpass.getpass("Repeat password: ")):
            sys.exit("Passwords do not match.")
        err = validate_new_user(db, username, email, pw)
        if err:
            sys.exit(err)
        create_user(db, username, email, pw, "admin")
        print("Admin created.")


def has_admin():
    """Exit code 0 if an admin account exists (start.bat uses this instead of 'does cpjudge.db exist')."""
    init_db()
    with SessionLocal() as db:
        ok = db.scalar(select(User.id).join(Role).where(Role.name == "admin").limit(1)) is not None
    sys.exit(0 if ok else 1)


def reset_admin():
    """Create the admin, or fix an existing account: new password, admin role, active, unlocked."""
    init_db()
    with SessionLocal() as db:
        username = input("Admin username (new or existing) [Jahonbek]: ").strip() or "Jahonbek"
        pw = getpass.getpass("New password (min 12 chars, not echoed): ")
        if len(pw) < 12:
            sys.exit("Password must be at least 12 characters.")
        if pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
        u = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
        if u:
            u.password_hash = hash_password(pw)
            u.role_id = db.scalar(select(Role.id).where(Role.name == "admin"))
            u.is_active, u.failed_logins, u.locked_until = True, 0, None
            db.commit()
            print(f"Account '{u.username}' is now an active admin with the new password.")
        else:
            err = validate_new_user(db, username, f"{username}@local.invalid", pw)
            if err:
                sys.exit(err)
            create_user(db, username, f"{username}@local.invalid", pw, "admin")
            print("Admin created.")


def seed_sample():
    init_db()
    runner = DockerRunner(load_settings().judge_image)
    with SessionLocal() as db:
        if db.scalar(select(Problem.id).where(Problem.title == "A + B")):
            sys.exit("Sample problem already exists.")
        admin = db.scalar(select(User).join(Role).where(Role.name == "admin").limit(1))
        p = Problem(title="A + B", difficulty="easy", rating=800, category="Basics", tags="math,implementation",
                    statement="Given two integers a and b, print their sum.", input_format="One line with two integers a and b.",
                    output_format="One integer: a + b.", constraints="-10^9 <= a, b <= 10^9", time_limit_ms=1000,
                    memory_limit_mb=256, created_by=admin.id if admin else None)
        db.add(p)
        db.flush()
        db.add(ReferenceSolution(problem_id=p.id, language="python3", source=SAMPLE_REFERENCE))
        db.commit()
        for inp, is_sample in (("1 2\n", True), ("-5 7\n", True)):
            print(testgen.add_manual(db, p, inp, "", is_sample, runner))
        rep = testgen.generate_tests(db, p, "python3", SAMPLE_GENERATOR, 25, runner)
        print(rep)
        if rep["total_valid"] >= testgen.MIN_VALID_TESTS:
            p.published = True
            db.commit()
            print("Sample problem published with", rep["total_valid"], "validated tests.")


def lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))   # no packet is sent; just picks the outgoing interface
        print(s.getsockname()[0])
    except OSError:
        print(socket.gethostbyname(socket.gethostname()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["init", "create-admin", "reset-admin", "has-admin", "seed-sample", "lan-ip"])
    c = ap.parse_args().cmd
    {"init": init_db, "create-admin": create_admin, "reset-admin": reset_admin, "has-admin": has_admin, "seed-sample": seed_sample, "lan-ip": lan_ip}[c]()
