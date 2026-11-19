from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc)


def aware(dt):
    """SQLite returns naive datetimes; we always store UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
