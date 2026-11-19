"""Platform-wide ranking (no DB, no web). A user's points are the sum of the ratings of the problems they solved;
the percent is that sum divided by the sum of ALL ratings currently available. Pure so it can be unit-tested."""
from dataclasses import dataclass


@dataclass
class GRow:
    user_id: int
    name: str
    avatar: str | None = None
    solved: int = 0
    points: int = 0
    percent: float = 0.0
    last_ac: object = None
    rank: int = 0


def compute_global(users, problems, first_ac):
    """users: [(user_id, name, avatar)]; problems: {problem_id: rating};
    first_ac: {(user_id, problem_id): datetime of the first accepted submission}."""
    total = sum(problems.values())
    rows = {uid: GRow(uid, name, avatar) for uid, name, avatar in users}
    for (uid, pid), t in first_ac.items():
        row = rows.get(uid)
        if row is None or pid not in problems:
            continue
        row.solved += 1
        row.points += problems[pid]
        if row.last_ac is None or t > row.last_ac:
            row.last_ac = t
    for r in rows.values():
        r.percent = round(100.0 * r.points / total, 1) if total else 0.0
    ordered = sorted(rows.values(), key=lambda r: (-r.points, -r.solved,
                                                   r.last_ac.timestamp() if r.last_ac else float("inf"),
                                                   r.name.lower()))
    for i, r in enumerate(ordered):   # equal points and equal solved count share a rank
        same = i > 0 and (ordered[i - 1].points, ordered[i - 1].solved) == (r.points, r.solved)
        r.rank = ordered[i - 1].rank if same else i + 1
    return ordered, total, len(problems)
