from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker
from .config import load_settings
from .models import Base, Permission, Role

settings = load_settings()
_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if _sqlite else {})
if _sqlite:
    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(engine, expire_on_commit=False)

PERMISSIONS = ["admin.access", "problems.manage", "contests.manage", "users.manage", "submissions.view_all"]


# Columns added after the first release. create_all() never alters existing tables, so old databases get them here.
_NEW_COLUMNS = {
    "problems": [("rating", "INTEGER NOT NULL DEFAULT 800")],
    "users": [("description", "TEXT NOT NULL DEFAULT ''"), ("avatar", "VARCHAR(64)")],
}


def _migrate():
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _NEW_COLUMNS.items():
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name in have:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                if (table, name) == ("problems", "rating"):   # keep old problems sensible: map the old label to a rating
                    conn.execute(text("UPDATE problems SET rating = CASE difficulty WHEN 'easy' THEN 800 "
                                      "WHEN 'medium' THEN 1200 ELSE 1800 END"))


def init_db():
    Base.metadata.create_all(engine)
    _migrate()
    with SessionLocal() as db:
        perms = {}
        for code in PERMISSIONS:
            p = db.scalar(select(Permission).where(Permission.code == code))
            if not p:
                p = Permission(code=code)
                db.add(p)
            perms[code] = p
        for name in ("admin", "student"):
            if not db.scalar(select(Role).where(Role.name == name)):
                r = Role(name=name)
                if name == "admin":
                    r.permissions = list(perms.values())
                db.add(r)
        db.commit()
