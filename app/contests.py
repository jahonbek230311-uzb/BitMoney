"""Contest rules. ALL timing decisions use server time (timeutil.now), never the client's clock."""
from fastapi import HTTPException
from sqlalchemy import select
from . import scoring
from .deps import user_perms
from .models import (Contest, ContestParticipant, ContestProblem, IgnoredSubmission, Problem, Submission, User)
from .timeutil import aware, now


def status(c, t=None):
    t = t or now()
    if c.state == "finished":
        return "finished"
    if c.state == "paused":
        return "paused"
    if t < aware(c.start_at):
        return "upcoming"
    return "running" if t < aware(c.end_at) else "finished"


def locked_problem_ids(db):
    """Problems of contests that have not finished: hidden from the general problem set."""
    t = now()
    rows = db.execute(select(ContestProblem.problem_id, Contest.state, Contest.end_at)
                      .join(Contest, Contest.id == ContestProblem.contest_id)).all()
    return {pid for pid, st, end in rows if st != "finished" and aware(end) > t}


def is_participant(db, cid, uid):
    return db.scalar(select(ContestParticipant.id).where(ContestParticipant.contest_id == cid,
                                                         ContestParticipant.user_id == uid)) is not None


def is_admin(user):
    return "admin.access" in user_perms(user)


def get_contest(db, cid):
    c = db.get(Contest, cid)
    if not c:
        raise HTTPException(404, "Contest not found")
    return c


def contest_problems(db, cid):
    rows = db.execute(select(ContestProblem, Problem).join(Problem, Problem.id == ContestProblem.problem_id)
                      .where(ContestProblem.contest_id == cid).order_by(ContestProblem.position)).all()
    return [(cp, p, chr(65 + i) if i < 26 else str(i + 1)) for i, (cp, p) in enumerate(rows)]


def can_view_problems(db, user, c):
    if is_admin(user):
        return True
    st = status(c)
    if st in ("upcoming", "paused"):
        return False
    if st == "finished":
        return True
    return c.kind == "practice" or is_participant(db, c.id, user.id)


def check_contest_access(db, user, cid, pid):
    """For run/submit with a contest_id. Raises HTTPException with a human message."""
    c = get_contest(db, cid)
    if not db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id == cid, ContestProblem.problem_id == pid)):
        raise HTTPException(404, "Problem is not part of this contest")
    if is_admin(user):
        return c
    st = status(c)
    if st == "upcoming":
        raise HTTPException(403, "The contest has not started yet.")
    if st == "paused":
        raise HTTPException(403, "The contest is paused.")
    if st == "finished" and c.kind != "practice":
        raise HTTPException(403, "The contest has finished.")
    if c.kind != "practice" and not is_participant(db, cid, user.id):
        raise HTTPException(403, "You are not registered for this contest.")
    return c


def access_problem(db, user, body):
    """Problem lookup for /api/run and /api/submit: published, not locked by a live contest (unless admin)."""
    p = db.get(Problem, body.problem_id)
    if not p:
        raise HTTPException(404, "Problem not found")
    if body.contest_id is not None:
        check_contest_access(db, user, body.contest_id, p.id)
        return p
    if not is_admin(user) and (not p.published or p.id in locked_problem_ids(db)):
        raise HTTPException(404, "Problem not found")
    return p


def build_standings(db, c, admin_view):
    probs = contest_problems(db, c.id)
    parts = db.execute(select(User.id, User.username).join(ContestParticipant, ContestParticipant.user_id == User.id)
                       .where(ContestParticipant.contest_id == c.id)).all()
    ignored = select(IgnoredSubmission.submission_id)
    subs = db.execute(select(Submission.id, Submission.user_id, Submission.problem_id, Submission.verdict,
                             Submission.created_at, Submission.passed, Submission.total)
                      .where(Submission.contest_id == c.id, Submission.id.not_in(ignored))).all()
    sl = [scoring.Sub(r[0], r[1], r[2], r[3], aware(r[4]), r[5], r[6]) for r in subs]
    frozen = c.frozen_at is not None
    cutoff = aware(c.frozen_at) if frozen and not admin_view else None
    rows = scoring.compute(c.scoring, c.penalty_minutes, c.partial_scoring, aware(c.start_at), aware(c.end_at),
                           [(cp.problem_id, cp.points) for cp, _, _ in probs], [(u, n) for u, n in parts], sl, cutoff)
    return rows, probs, frozen


def standings_json(db, c, user):
    admin = is_admin(user)
    st = status(c)
    base = {"status": st, "server_now": now().isoformat(), "contest": c.title, "scoring": c.scoring}
    if c.kind == "private" and not admin and not is_participant(db, c.id, user.id):
        raise HTTPException(403, "Private contest")
    if c.scoreboard_hidden and st != "finished" and not admin:
        return {**base, "hidden": True}
    rows, probs, frozen = build_standings(db, c, admin)
    return {**base, "hidden": False, "frozen": frozen, "admin_view": admin,
            "problems": [{"id": p.id, "letter": l, "title": p.title, "points": cp.points} for cp, p, l in probs],
            "rows": [{"rank": r.rank, "user": r.name, "solved": r.solved, "tried": r.tried, "score": r.score, "penalty": r.penalty,
                      "cells": [{"solved": r.cells[cp.problem_id].solved, "wrong": r.cells[cp.problem_id].wrong,
                                 "minutes": r.cells[cp.problem_id].minutes, "points": r.cells[cp.problem_id].points}
                                for cp, _, _ in probs]} for r in rows]}
