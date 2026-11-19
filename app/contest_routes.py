import csv, io, re
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select

from . import testgen
from .common import audit, render
from .contests import (build_standings, can_view_problems, contest_problems, get_contest, is_admin, is_participant,
                       standings_json, status)
from .db import SessionLocal  # noqa: F401
from .deps import get_db, login_required, require_perm
from .models import (Contest, ContestParticipant, ContestProblem, Problem, Role, Submission, TestCase, User)
from .ratelimit import RateLimiter
from .security import hash_password, verify_password
from .timeutil import aware, now

router = APIRouter()
contests_dep = require_perm("contests.manage")
join_limiter = RateLimiter(8, 60)


def go(url, msg):
    return RedirectResponse(url + "?msg=" + quote_plus(msg), 303)


def parse_iso(s):
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid date/time")
    return d if d.tzinfo else d.astimezone(timezone.utc)   # naive = server's local time (fallback when JS did not run)


# ---------------- student side ----------------
@router.get("/contests", response_class=HTMLResponse)
def contests_page(request: Request, user=Depends(login_required), db=Depends(get_db)):
    mine = set(db.scalars(select(ContestParticipant.contest_id).where(ContestParticipant.user_id == user.id)))
    items = [(c, status(c), c.id in mine) for c in db.scalars(select(Contest).order_by(Contest.start_at.desc()))]
    return render(request, "contests.html", user, current=[i for i in items if i[1] != "finished"],
                  past=[i for i in items if i[1] == "finished"], server_now=now().isoformat())


@router.get("/contests/{cid}", response_class=HTMLResponse)
def contest_page(cid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    c = get_contest(db, cid)
    st = status(c)
    part = is_participant(db, cid, user.id)
    visible = can_view_problems(db, user, c)
    probs = contest_problems(db, cid) if visible else []
    solved = set()
    if probs:
        solved = set(db.scalars(select(Submission.problem_id).where(Submission.contest_id == cid, Submission.user_id == user.id,
                                                                    Submission.verdict == "AC")))
    n = db.scalar(select(func.count()).select_from(ContestParticipant).where(ContestParticipant.contest_id == cid))
    target = c.start_at if st == "upcoming" else c.end_at
    return render(request, "contest.html", user, c=c, st=st, part=part, probs=probs, solved=solved, n=n,
                  server_now=now().isoformat(), target=aware(target).isoformat() if st in ("upcoming", "running") else "")


@router.post("/contests/{cid}/join")
def contest_join(cid: int, request: Request, password: str = Form(""), user=Depends(login_required), db=Depends(get_db)):
    if not join_limiter.allow(user.id):
        raise HTTPException(429, "Too many attempts")
    c = get_contest(db, cid)
    url = f"/contests/{cid}"
    if is_participant(db, cid, user.id):
        return go(url, "You are already registered.")
    if status(c) == "finished" and c.kind != "practice":
        return go(url, "This contest has finished.")
    if c.registration_deadline and now() > aware(c.registration_deadline):
        return go(url, "Registration is closed.")
    if c.max_participants:
        n = db.scalar(select(func.count()).select_from(ContestParticipant).where(ContestParticipant.contest_id == cid))
        if n >= c.max_participants:
            return go(url, "The contest is full.")
    if c.kind == "private" and not (c.password_hash and verify_password(password, c.password_hash)):
        return go(url, "Wrong contest password.")
    db.add(ContestParticipant(contest_id=cid, user_id=user.id))
    db.commit()
    return go(url, "Registered. Good luck!")


@router.get("/contests/{cid}/problems/{pid}", response_class=HTMLResponse)
def contest_problem(cid: int, pid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    c = get_contest(db, cid)
    if not can_view_problems(db, user, c):
        raise HTTPException(403, "Problems are not available to you right now (not registered, not started, or paused).")
    if not db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id == cid, ContestProblem.problem_id == pid)):
        raise HTTPException(404, "Problem is not part of this contest")
    p = db.get(Problem, pid)
    samples = db.scalars(select(TestCase).where(TestCase.problem_id == pid, TestCase.is_sample.is_(True),
                                                TestCase.validated.is_(True)).order_by(TestCase.ordinal)).all()
    st = status(c)
    return render(request, "problem.html", user, p=p, samples=samples, contest=c, server_now=now().isoformat(),
                  target=aware(c.end_at).isoformat() if st == "running" else "")


@router.get("/contests/{cid}/standings", response_class=HTMLResponse)
def standings_page(cid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    c = get_contest(db, cid)
    return render(request, "standings.html", user, c=c, st=status(c))


@router.get("/api/contests/{cid}/standings")
def standings_api(cid: int, user=Depends(login_required), db=Depends(get_db)):
    return standings_json(db, get_contest(db, cid), user)


@router.get("/contests/{cid}/submissions", response_class=HTMLResponse)
def contest_submissions(cid: int, request: Request, user=Depends(login_required), db=Depends(get_db)):
    c = get_contest(db, cid)
    rows = db.execute(select(Submission, Problem.title).join(Problem, Problem.id == Submission.problem_id)
                      .where(Submission.contest_id == cid, Submission.user_id == user.id)
                      .order_by(Submission.id.desc())).all()
    from .models import IgnoredSubmission
    return render(request, "submissions.html", user, rows=rows, title=f"My submissions: {c.title}", show_user=False,
                  ignored=set(db.scalars(select(IgnoredSubmission.submission_id))), admin_actions=False)


# ---------------- admin side ----------------
def contest_form(title: str = Form(...), description: str = Form(""), rules: str = Form(""),
                 kind: Literal["public", "private", "practice"] = Form("public"), password: str = Form(""),
                 start_iso: str = Form(""), start_local: str = Form(""), duration_minutes: int = Form(...),
                 registration_deadline_iso: str = Form(""), registration_deadline_local: str = Form(""),
                 max_participants: str = Form(""), scoring: Literal["icpc", "points"] = Form("icpc"),
                 penalty_minutes: int = Form(20), partial_scoring: str = Form("")):
    if not title.strip():
        raise HTTPException(400, "Title is required")
    if not 1 <= duration_minutes <= 20160:
        raise HTTPException(400, "Duration must be between 1 minute and 14 days")
    if not 0 <= penalty_minutes <= 600:
        raise HTTPException(400, "Penalty must be 0-600 minutes")
    mp = None
    if max_participants.strip():
        if not max_participants.strip().isdigit() or int(max_participants) < 1:
            raise HTTPException(400, "Participant limit must be a positive number")
        mp = int(max_participants)
    start_raw = (start_iso or start_local).strip()
    if not start_raw:
        raise HTTPException(400, "Start time is required")
    start = parse_iso(start_raw)
    deadline_raw = (registration_deadline_iso or registration_deadline_local).strip()
    return dict(title=title.strip()[:200], description=description, rules=rules, kind=kind, password=password,
                start_at=start, end_at=start + timedelta(minutes=duration_minutes),
                registration_deadline=parse_iso(deadline_raw) if deadline_raw else None,
                max_participants=mp, scoring=scoring, penalty_minutes=penalty_minutes,
                partial_scoring=(partial_scoring == "on" and scoring == "points"))


def apply_form(c, v, creating):
    pw = v.pop("password")
    for k, val in v.items():
        setattr(c, k, val)
    if c.kind == "private":
        if pw:
            if len(pw) < 4:
                raise HTTPException(400, "Contest password must be at least 4 characters")
            c.password_hash = hash_password(pw)
        elif creating or not c.password_hash:
            raise HTTPException(400, "A private contest needs a password")
    else:
        c.password_hash = None


@router.get("/admin/contests", response_class=HTMLResponse)
def admin_contests(request: Request, user=Depends(contests_dep), db=Depends(get_db)):
    rows = []
    for c in db.scalars(select(Contest).order_by(Contest.start_at.desc())):
        n = db.scalar(select(func.count()).select_from(ContestParticipant).where(ContestParticipant.contest_id == c.id))
        k = db.scalar(select(func.count()).select_from(ContestProblem).where(ContestProblem.contest_id == c.id))
        rows.append((c, status(c), n, k))
    return render(request, "admin_contests.html", user, rows=rows)


@router.get("/admin/contests/new", response_class=HTMLResponse)
def admin_contest_new(request: Request, user=Depends(contests_dep)):
    return render(request, "admin_contest_new.html", user, c=None)


@router.post("/admin/contests")
def admin_contest_create(request: Request, v=Depends(contest_form), user=Depends(contests_dep), db=Depends(get_db)):
    c = Contest(created_by=user.id)
    apply_form(c, v, True)
    db.add(c)
    db.flush()
    audit(db, user, "contest.create", c.id, c.title, request)
    db.commit()
    return go(f"/admin/contests/{c.id}", "Contest created. Now add problems and participants.")


@router.get("/admin/contests/{cid}", response_class=HTMLResponse)
def admin_contest(cid: int, request: Request, user=Depends(contests_dep), db=Depends(get_db)):
    c = get_contest(db, cid)
    probs = contest_problems(db, cid)
    used = {cp.problem_id for cp, _, _ in probs}
    candidates = [(p, testgen.readiness(db, p)[0]) for p in db.scalars(select(Problem).order_by(Problem.id))
                  if p.id not in used]
    parts = db.scalars(select(User).join(ContestParticipant, ContestParticipant.user_id == User.id)
                       .where(ContestParticipant.contest_id == cid).order_by(User.username)).all()
    pids = {u.id for u in parts}
    others = [u for u in db.scalars(select(User).join(Role).where(Role.name == "student", User.is_active.is_(True))
                                    .order_by(User.username)) if u.id not in pids]
    counts = dict(db.execute(select(Submission.verdict, func.count()).where(Submission.contest_id == cid)
                             .group_by(Submission.verdict)).all())
    return render(request, "admin_contest.html", user, c=c, st=status(c), probs=probs, candidates=candidates, parts=parts,
                  others=others, counts=counts, server_now=now().isoformat(), min_tests=testgen.MIN_VALID_TESTS)


@router.post("/admin/contests/{cid}/update")
def admin_contest_update(cid: int, request: Request, v=Depends(contest_form), user=Depends(contests_dep), db=Depends(get_db)):
    c = get_contest(db, cid)
    apply_form(c, v, False)
    audit(db, user, "contest.update", cid, request=request)
    db.commit()
    return go(f"/admin/contests/{cid}", "Saved.")


def _control(cid, request, user, db, action):
    c = get_contest(db, cid)
    t, st = now(), status(c)
    dur = aware(c.end_at) - aware(c.start_at)
    msg = "Done."
    if action == "start":
        if st != "upcoming":
            return go(f"/admin/contests/{cid}", "Only an upcoming contest can be started.")
        c.start_at, c.end_at, c.state = t, t + dur, "scheduled"
        msg = "Contest started now."
    elif action == "pause":
        if st != "running":
            return go(f"/admin/contests/{cid}", "Only a running contest can be paused.")
        c.state, c.paused_at = "paused", t
        msg = "Paused. The clock is stopped and submissions are rejected."
    elif action == "resume":
        if c.state != "paused":
            return go(f"/admin/contests/{cid}", "The contest is not paused.")
        c.end_at = aware(c.end_at) + (t - aware(c.paused_at))
        c.state, c.paused_at = "scheduled", None
        msg = "Resumed. The end time was extended by the pause length."
    elif action == "finish":
        if st == "finished":
            return go(f"/admin/contests/{cid}", "Already finished.")
        c.state = "finished"
        if aware(c.end_at) > t:
            c.end_at = t
        msg = "Contest finished."
    elif action == "hide":
        c.scoreboard_hidden, msg = True, "Scoreboard hidden from students until the contest finishes."
    elif action == "show":
        c.scoreboard_hidden, msg = False, "Scoreboard visible."
    elif action == "freeze":
        c.frozen_at, msg = t, "Scoreboard frozen for students (admins still see the live board)."
    elif action == "unfreeze":
        c.frozen_at, msg = None, "Scoreboard unfrozen."
    audit(db, user, "contest." + action, cid, request=request)
    db.commit()
    return go(f"/admin/contests/{cid}", msg)


for _a in ("start", "pause", "resume", "finish", "hide", "show", "freeze", "unfreeze"):
    def _mk(a):
        def h(cid: int, request: Request, user=Depends(contests_dep), db=Depends(get_db)):
            return _control(cid, request, user, db, a)
        return h
    router.add_api_route(f"/admin/contests/{{cid}}/{_a}", _mk(_a), methods=["POST"])


@router.post("/admin/contests/{cid}/delete")
def admin_contest_delete(cid: int, request: Request, user=Depends(contests_dep), db=Depends(get_db)):
    c = get_contest(db, cid)
    audit(db, user, "contest.delete", cid, c.title, request)
    db.delete(c)
    db.commit()
    return go("/admin/contests", "Contest deleted.")


@router.post("/admin/contests/{cid}/problems/add")
def admin_cp_add(cid: int, request: Request, problem_id: int = Form(...), points: str = Form(""),
                 user=Depends(contests_dep), db=Depends(get_db)):
    get_contest(db, cid)
    p = db.get(Problem, problem_id)
    if not p:
        raise HTTPException(404, "Problem not found")
    issues, _ = testgen.readiness(db, p)
    if issues:   # automatic check: the problem must be complete before it can join a contest
        return go(f"/admin/contests/{cid}", f"Problem #{p.id} is not ready: " + "; ".join(issues) + ".")
    if db.scalar(select(ContestProblem.id).where(ContestProblem.contest_id == cid, ContestProblem.problem_id == p.id)):
        return go(f"/admin/contests/{cid}", "Already in this contest.")
    pts = int(points) if points.strip().isdigit() else (p.rating if not points.strip() else 0)   # blank = problem rating
    if not 1 <= pts <= 100000:
        return go(f"/admin/contests/{cid}", "Points must be 1-100000.")
    pos = (db.scalar(select(func.max(ContestProblem.position)).where(ContestProblem.contest_id == cid)) or 0) + 1
    db.add(ContestProblem(contest_id=cid, problem_id=p.id, position=pos, points=pts))
    audit(db, user, "contest.problem_add", cid, p.id, request=request)
    db.commit()
    return go(f"/admin/contests/{cid}", "Problem added.")


@router.post("/admin/contests/{cid}/problems/{cpid}/points")
def admin_cp_points(cid: int, cpid: int, points: int = Form(...), user=Depends(contests_dep), db=Depends(get_db)):
    cp = db.get(ContestProblem, cpid)
    if not cp or cp.contest_id != cid or not 1 <= points <= 100000:
        raise HTTPException(400, "Invalid request")
    cp.points = points
    db.commit()
    return go(f"/admin/contests/{cid}", "Points updated.")


@router.post("/admin/contests/{cid}/problems/{cpid}/remove")
def admin_cp_remove(cid: int, cpid: int, request: Request, user=Depends(contests_dep), db=Depends(get_db)):
    cp = db.get(ContestProblem, cpid)
    if not cp or cp.contest_id != cid:
        raise HTTPException(404, "Not found")
    db.delete(cp)
    audit(db, user, "contest.problem_remove", cid, cp.problem_id, request=request)
    db.commit()
    return go(f"/admin/contests/{cid}", "Problem removed.")


@router.post("/admin/contests/{cid}/problems/{cpid}/move")
def admin_cp_move(cid: int, cpid: int, direction: Literal["up", "down"] = Form(...), user=Depends(contests_dep),
                  db=Depends(get_db)):
    cp = db.get(ContestProblem, cpid)
    if not cp or cp.contest_id != cid:
        raise HTTPException(404, "Not found")
    q = select(ContestProblem).where(ContestProblem.contest_id == cid)
    q = (q.where(ContestProblem.position < cp.position).order_by(ContestProblem.position.desc()) if direction == "up"
         else q.where(ContestProblem.position > cp.position).order_by(ContestProblem.position))
    other = db.scalar(q.limit(1))
    if other:
        pa, pb = cp.position, other.position
        cp.position = -cp.id          # avoid the UNIQUE(contest, position) clash while swapping
        db.flush()
        other.position = pa
        db.flush()
        cp.position = pb
        db.commit()
    return go(f"/admin/contests/{cid}", "Order updated.")


@router.post("/admin/contests/{cid}/participants/add")
def admin_part_add(cid: int, request: Request, user_ids: list[int] = Form([]), all_students: str = Form(""),
                   usernames: str = Form(""), user=Depends(contests_dep), db=Depends(get_db)):
    get_contest(db, cid)
    wanted = set(user_ids)
    if all_students == "1":
        wanted |= set(db.scalars(select(User.id).join(Role).where(Role.name == "student", User.is_active.is_(True))))
    unknown = []
    for name in {n for n in re.split(r"[\s,;]+", usernames) if n}:   # pasted list: one per line or comma separated
        uid = db.scalar(select(User.id).where(User.username == name, User.is_active.is_(True)))
        if uid is None:
            unknown.append(name)
        else:
            wanted.add(uid)
    have = set(db.scalars(select(ContestParticipant.user_id).where(ContestParticipant.contest_id == cid)))
    added = 0
    for uid in wanted - have:
        if db.get(User, uid):
            db.add(ContestParticipant(contest_id=cid, user_id=uid))
            added += 1
    audit(db, user, "contest.participants_add", cid, str(added), request=request)
    db.commit()
    msg = f"{added} participant(s) registered."
    if unknown:
        msg += " Unknown usernames: " + ", ".join(sorted(unknown)[:10]) + ("..." if len(unknown) > 10 else "")
    return go(f"/admin/contests/{cid}", msg)


@router.post("/admin/contests/{cid}/participants/{uid}/remove")
def admin_part_remove(cid: int, uid: int, request: Request, user=Depends(contests_dep), db=Depends(get_db)):
    cp = db.scalar(select(ContestParticipant).where(ContestParticipant.contest_id == cid, ContestParticipant.user_id == uid))
    if cp:
        db.delete(cp)
        audit(db, user, "contest.participant_remove", cid, uid, request=request)
        db.commit()
    return go(f"/admin/contests/{cid}", "Participant removed.")


@router.get("/admin/contests/{cid}/export.csv")
def admin_export(cid: int, user=Depends(contests_dep), db=Depends(get_db)):
    c = get_contest(db, cid)
    rows, probs, _ = build_standings(db, c, True)

    def safe(x):
        x = str(x)
        return "'" + x if x[:1] in ("=", "+", "-", "@") else x
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Rank", "User"] + [l for _, _, l in probs] + ["Penalty", "Tried", "Solved"] + (["Score"] if c.scoring == "points" else []))
    for r in rows:
        cells = []
        for cp, _, _ in probs:
            x = r.cells[cp.problem_id]
            cells.append((f"+{x.wrong}" if x.wrong else "+") if x.solved else (f"-{x.wrong}" if x.wrong else ""))
        w.writerow([r.rank, safe(r.name)] + cells + [r.penalty, r.tried, r.solved] + ([r.score] if c.scoring == "points" else []))
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="contest_{cid}_results.csv"'})
