"""Problem ratings (Codeforces style). The admin picks a rating when adding a problem; the old
easy/medium/hard label is derived from it so filters and profile statistics keep working."""

MIN_RATING, MAX_RATING = 800, 3500
CHOICES = list(range(MIN_RATING, MAX_RATING + 1, 100))   # 800, 900, 1000, ... 3500


def valid(r) -> bool:
    return isinstance(r, int) and MIN_RATING <= r <= MAX_RATING


def difficulty_for(r: int) -> str:
    return "easy" if r <= 1100 else "medium" if r <= 1700 else "hard"
