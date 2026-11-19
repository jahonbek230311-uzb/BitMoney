"""Pure contest scoring (no DB, no web). ICPC and points modes, freeze cutoff, ties.
ICPC penalty = number of failed attempts on solved problems (time does not matter); penalty_minutes is kept only for
backward compatibility and is ignored."""
from dataclasses import dataclass, field

COUNTED = {"AC", "WA", "TLE", "MLE", "RE"}  # CE / SE / PENDING / JUDGING never count as attempts


@dataclass
class Sub:
    id: int
    user_id: int
    problem_id: int
    verdict: str
    created_at: object
    passed: int = 0
    total: int = 0


@dataclass
class Cell:
    solved: bool = False
    wrong: int = 0
    minutes: int | None = None
    points: float = 0.0


@dataclass
class Row:
    user_id: int
    name: str
    cells: dict = field(default_factory=dict)
    solved: int = 0
    tried: int = 0          # problems with at least one counted attempt
    score: float = 0.0
    penalty: int = 0        # ICPC: number of wrong attempts on solved problems (not minutes)
    last_ac: int = 0
    rank: int = 0


def compute(mode, penalty_minutes, partial, start, end, problems, participants, subs, cutoff=None):
    """problems: [(problem_id, points)] in display order; participants: [(user_id, name)].
    Counted submissions: start <= created_at <= end (and < cutoff when the board is frozen)."""
    pts = dict(problems)
    partial = bool(partial) and mode == "points"
    rows = {uid: Row(uid, name, {pid: Cell() for pid, _ in problems}) for uid, name in participants}
    for s in sorted(subs, key=lambda x: (x.created_at, x.id)):
        row = rows.get(s.user_id)
        if row is None or s.problem_id not in pts or s.verdict not in COUNTED:
            continue
        if s.created_at < start or (end is not None and s.created_at > end):
            continue
        if cutoff is not None and s.created_at >= cutoff:
            continue
        cell = row.cells[s.problem_id]
        if cell.solved:
            continue
        if s.verdict == "AC":
            cell.solved = True
            cell.minutes = int((s.created_at - start).total_seconds() // 60)
            cell.points = float(pts[s.problem_id])
        else:
            cell.wrong += 1
            if partial and s.total:
                cell.points = max(cell.points, round(pts[s.problem_id] * s.passed / s.total, 2))
    for row in rows.values():
        for cell in row.cells.values():
            if cell.solved or cell.wrong:
                row.tried += 1
            if cell.solved:
                row.solved += 1
                row.penalty += cell.wrong          # penalty = failed attempts, never time
                row.last_ac = max(row.last_ac, cell.minutes)
            if mode == "points":
                row.score += cell.points
        if mode == "icpc":
            row.score = float(row.solved)
        row.score = round(row.score, 2)
    # rank by solved/score, then fewer failed attempts; equal results share a place (earlier last solve only orders them)
    ordered = sorted(rows.values(), key=lambda r: (-r.score, r.penalty, r.last_ac, r.name.lower()))
    prev = None
    for i, r in enumerate(ordered):
        key = (r.score, r.penalty)
        r.rank = ordered[i - 1].rank if prev == key else i + 1
        prev = key
    return ordered
