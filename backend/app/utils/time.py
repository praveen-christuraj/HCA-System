"""Time helpers.

The application stores naive UTC timestamps so that PostgreSQL and SQLite
behave identically in tests and in production.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (database representation)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def day_start(value: date | datetime) -> datetime:
    return datetime.combine(value if isinstance(value, date) else value.date(), time.min)


def day_end(value: date | datetime) -> datetime:
    return datetime.combine(value if isinstance(value, date) else value.date(), time.max)
