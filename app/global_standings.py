from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from .common import render
from .contests import locked_problem_ids
from .deps import get_db, login_required
from .models import IgnoredSubmission, Problem, Role, Submission, User
from .ranking import compute_global
from .timeutil import aware

router = APIRouter()


def build_global(db):
    locked = locked_problem_ids(db)   # problems of a running contest do not count until that contest is over
    problems = {pid: rating for pid, rating in db.execute(select(Problem.id, Problem.rating).where(Problem.published.is_(True)))
                if pid not in locked}
    ignored = select(IgnoredSubmission.submission_id)
    ac = db.execute(select(Submission.user_id, Submission.problem_id, func.min(Submission.created_at))
                    .where(Submission.verdict == "AC", Submission.id.not_in(ignored))
                    .group_by(Submission.user_id, Submission.problem_id)).all()
    first_ac = {(u, p): aware(t) for u, p, t in ac if p in problems}
    users = db.execute(select(User.id, User.username, User.avatar).join(Role, Role.id == User.role_id)
                       .where(Role.name == "student", User.is_active.is_(True))).all()
    return compute_global([(u, n, a) for u, n, a in users], problems, first_ac)


@router.get("/standings", response_class=HTMLResponse)
def global_standings(request: Request, user=Depends(login_required), db=Depends(get_db)):
    rows, total_points, total_count = build_global(db)
    name = "_global_board.html" if request.query_params.get("partial") else "global_standings.html"
    return render(request, name, user, rows=rows, total_points=total_points, total_count=total_count, me=user.username)
