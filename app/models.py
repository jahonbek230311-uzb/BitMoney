"""Full schema (SQLAlchemy 2.0). Times are stored UTC; contest logic uses SERVER time only."""
from datetime import datetime, timezone
from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer,
                        String, Table, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True))


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    permissions = relationship("Permission", secondary=role_permissions, lazy="selectin")


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar: Mapped[str | None] = mapped_column(String(64))
    role = relationship("Role", lazy="joined")


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Problem(Base):
    __tablename__ = "problems"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    examples_json: Mapped[str] = mapped_column(Text, default="[]")
    difficulty: Mapped[str] = mapped_column(String(8))   # derived from rating (see ratings.py)
    rating: Mapped[int] = mapped_column(Integer, default=800)   # Codeforces-style: 800, 900, 1000, 1200, ...
    category: Mapped[str] = mapped_column(String(64), default="", index=True)
    tags: Mapped[str] = mapped_column(String(255), default="")
    time_limit_ms: Mapped[int] = mapped_column(Integer, default=1000)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=256)
    checker_mode: Mapped[str] = mapped_column(String(8), default="tokens")
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("difficulty IN ('easy','medium','hard')"),
                      CheckConstraint("time_limit_ms BETWEEN 100 AND 20000"),
                      CheckConstraint("memory_limit_mb BETWEEN 16 AND 1024"))
    test_cases = relationship("TestCase", cascade="all, delete-orphan", back_populates="problem")


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    input_data: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(16), default="manual")  # manual|generated|edge|max
    source: Mapped[str] = mapped_column(String(16), default="admin")  # admin|reference|approved
    input_hash: Mapped[str] = mapped_column(String(64))
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    problem = relationship("Problem", back_populates="test_cases")
    __table_args__ = (UniqueConstraint("problem_id", "input_hash"), UniqueConstraint("problem_id", "ordinal"))


class ReferenceSolution(Base):
    __tablename__ = "reference_solutions"
    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Contest(Base):
    __tablename__ = "contests"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    rules: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(8), default="public")  # public|private|practice
    password_hash: Mapped[str | None] = mapped_column(String(255))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_participants: Mapped[int | None] = mapped_column(Integer)
    scoring: Mapped[str] = mapped_column(String(8), default="icpc")  # icpc|points
    penalty_minutes: Mapped[int] = mapped_column(Integer, default=20)
    partial_scoring: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(10), default="scheduled")  # scheduled|running|paused|finished
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scoreboard_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (CheckConstraint("end_at > start_at"),
                      CheckConstraint("kind IN ('public','private','practice')"))


class ContestProblem(Base):
    __tablename__ = "contest_problems"
    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer, default=100)
    __table_args__ = (UniqueConstraint("contest_id", "problem_id"), UniqueConstraint("contest_id", "position"))


class ContestParticipant(Base):
    __tablename__ = "contest_participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("contest_id", "user_id"),)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"))
    contest_id: Mapped[int | None] = mapped_column(ForeignKey("contests.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(8), default="PENDING")
    compile_log: Mapped[str] = mapped_column(Text, default="")
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    memory_kb: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results = relationship("TestResult", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_sub_user_problem", "user_id", "problem_id"),
                      Index("ix_sub_contest", "contest_id", "created_at"),
                      CheckConstraint("verdict IN ('PENDING','JUDGING','AC','WA','TLE','MLE','RE','CE','SE')"))


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"))
    verdict: Mapped[str] = mapped_column(String(8))
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    memory_kb: Mapped[int] = mapped_column(Integer, default=0)


class ContestRanking(Base):
    __tablename__ = "contest_rankings"
    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float, default=0)
    penalty: Mapped[int] = mapped_column(Integer, default=0)
    solved: Mapped[int] = mapped_column(Integer, default=0)
    last_ac_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("contest_id", "user_id"),
                      Index("ix_rank_order", "contest_id", "score", "penalty"))


class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int | None] = mapped_column(ForeignKey("contests.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class IgnoredSubmission(Base):
    """Admin 'cancel/ignore': the submission stays in history but never counts (standings, stats)."""
    __tablename__ = "ignored_submissions"
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True)
    by_user: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProfileRequest(Base):
    """A profile change a student asked for. It only takes effect after an admin accepts it.
    kind: avatar (value = stored file name) | description | email | password (value = scrypt hash, never plaintext)."""
    __tablename__ = "profile_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)   # pending|accepted|rejected
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (CheckConstraint("kind IN ('avatar','description','email','password')"),
                      CheckConstraint("status IN ('pending','accepted','rejected')"))
