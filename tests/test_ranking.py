import unittest
from datetime import datetime, timedelta, timezone

from app.ranking import compute_global
from app.ratings import difficulty_for, valid

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Ranking(unittest.TestCase):
    def test_points_percent_and_order(self):
        users = [(1, "ali", None), (2, "vali", None), (3, "zed", None), (4, "bob", None)]
        probs = {10: 800, 11: 1000, 12: 1200}
        ac = {(1, 10): T, (1, 11): T + timedelta(hours=1), (2, 12): T, (2, 10): T, (3, 10): T}
        rows, total, count = compute_global(users, probs, ac)
        self.assertEqual((total, count), (3000, 3))
        self.assertEqual([(r.name, r.points, r.solved, r.rank) for r in rows],
                         [("vali", 2000, 2, 1), ("ali", 1800, 2, 2), ("zed", 800, 1, 3), ("bob", 0, 0, 4)])
        self.assertEqual([r.percent for r in rows], [66.7, 60.0, 26.7, 0.0])

    def test_ties_share_a_rank_and_empty_pool(self):
        users = [(1, "a", None), (2, "b", None)]
        rows, total, _ = compute_global(users, {10: 800}, {(1, 10): T, (2, 10): T + timedelta(hours=1)})
        self.assertEqual([r.rank for r in rows], [1, 1])
        rows, total, _ = compute_global(users, {}, {})
        self.assertEqual((total, [r.percent for r in rows]), (0, [0.0, 0.0]))

    def test_unavailable_problem_and_unknown_user_ignored(self):
        rows, _, _ = compute_global([(1, "a", None)], {10: 800}, {(1, 99): T, (7, 10): T})
        self.assertEqual((rows[0].solved, rows[0].points), (0, 0))

    def test_rating_helpers(self):
        self.assertTrue(valid(800) and valid(3500) and not valid(799) and not valid(3501))
        self.assertEqual([difficulty_for(r) for r in (800, 1100, 1200, 1700, 1800)], ["easy", "easy", "medium", "medium", "hard"])


if __name__ == "__main__":
    unittest.main()
