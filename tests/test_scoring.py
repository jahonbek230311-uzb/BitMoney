import unittest
from datetime import datetime, timedelta, timezone
from app.scoring import Sub, compute

S = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
E = S + timedelta(hours=2)
P = [(1, 100), (2, 200)]
U = [(10, "alice"), (11, "bob"), (12, "carol")]
_id = [0]


def sub(u, p, v, minute, passed=0, total=0):
    _id[0] += 1
    return Sub(_id[0], u, p, v, S + timedelta(minutes=minute, seconds=30), passed, total)


def run(subs, **kw):
    a = dict(mode="icpc", penalty_minutes=20, partial=False, start=S, end=E, problems=P, participants=U, subs=subs)
    a.update(kw)
    return {r.name: r for r in compute(**a)}


class Scoring(unittest.TestCase):
    def test_icpc_penalty(self):
        r = run([sub(10, 1, "WA", 5), sub(10, 1, "TLE", 8), sub(10, 1, "AC", 30), sub(10, 2, "AC", 50)])
        a = r["alice"]
        self.assertEqual((a.solved, a.rank), (2, 1))
        self.assertEqual(a.penalty, 2)   # failed attempts only, not minutes
        self.assertEqual(a.tried, 2)
        self.assertEqual(a.cells[1].wrong, 2)

    def test_ce_and_pending_not_counted(self):
        r = run([sub(10, 1, "CE", 1), sub(10, 1, "SE", 2), sub(10, 1, "PENDING", 3), sub(10, 1, "AC", 10)])
        self.assertEqual((r["alice"].cells[1].wrong, r["alice"].penalty), (0, 0))

    def test_after_ac_ignored(self):
        r = run([sub(10, 1, "AC", 10), sub(10, 1, "WA", 20), sub(10, 1, "AC", 25)])
        self.assertEqual((r["alice"].penalty, r["alice"].cells[1].wrong), (0, 0))

    def test_unsolved_wrong_attempts_cost_nothing(self):
        r = run([sub(10, 1, "WA", 5), sub(10, 1, "WA", 6)])
        self.assertEqual((r["alice"].solved, r["alice"].penalty, r["alice"].tried), (0, 0, 1))

    def test_ranking_and_ties(self):
        r = run([sub(10, 1, "AC", 10), sub(11, 1, "AC", 50), sub(12, 1, "WA", 5), sub(12, 1, "AC", 20)])
        self.assertEqual((r["alice"].rank, r["bob"].rank, r["carol"].rank), (1, 1, 3))   # time never matters, only failures
        r = run([sub(10, 1, "AC", 10), sub(10, 2, "AC", 11), sub(11, 1, "AC", 5)])
        self.assertEqual((r["alice"].rank, r["bob"].rank), (1, 2))   # more solved beats less penalty

    def test_outside_window_ignored(self):
        early = Sub(900, 10, 1, "AC", S - timedelta(minutes=1))
        late = Sub(901, 10, 1, "AC", E + timedelta(seconds=1))
        r = run([early, late])
        self.assertEqual(r["alice"].solved, 0)

    def test_freeze_cutoff(self):
        subs = [sub(10, 1, "AC", 10), sub(11, 1, "AC", 100)]
        frozen = run(subs, cutoff=S + timedelta(minutes=60))
        self.assertEqual((frozen["alice"].solved, frozen["bob"].solved), (1, 0))
        self.assertEqual(run(subs)["bob"].solved, 1)

    def test_points_mode_partial(self):
        subs = [sub(10, 1, "AC", 10), sub(11, 2, "WA", 10, passed=10, total=20), sub(11, 2, "WA", 12, passed=5, total=20)]
        r = run(subs, mode="points", partial=True)
        self.assertEqual((r["alice"].score, r["bob"].score), (100.0, 100.0))
        r2 = run(subs, mode="points", partial=False)
        self.assertEqual(r2["bob"].score, 0.0)

    def test_participants_with_no_submissions_listed(self):
        self.assertEqual(len(run([])), 3)

    def test_other_users_and_problems_ignored(self):
        r = run([sub(99, 1, "AC", 5), sub(10, 77, "AC", 5)])
        self.assertTrue(all(x.solved == 0 for x in r.values()))


if __name__ == "__main__":
    unittest.main()
