"""When the scheduled Moodle pull is due. Manual sync does not use this clock."""

from datetime import UTC, datetime, timedelta

ALLOWED_MINUTES = (15, 30, 60, 120)


def normalize_minutes(value: int) -> int:
    return value if value in ALLOWED_MINUTES else 30


def normalize_hour(value: int) -> int:
    return min(23, max(0, int(value)))


def next_incremental(
    last: datetime | None, minutes: int, paused: bool, now: datetime | None = None
) -> datetime | None:
    if paused:
        return None
    current = now or datetime.now(UTC)
    if last is None or last + timedelta(minutes=normalize_minutes(minutes)) <= current:
        return current
    return last + timedelta(minutes=normalize_minutes(minutes))


def next_nightly(hour: int, enabled: bool, now: datetime | None = None) -> datetime | None:
    if not enabled:
        return None
    current = now or datetime.now(UTC)
    slot = current.replace(hour=normalize_hour(hour), minute=0, second=0, microsecond=0)
    if slot <= current:
        slot += timedelta(days=1)
    return slot


def incremental_due(
    last: datetime | None, minutes: int, paused: bool, now: datetime | None = None
) -> bool:
    if paused:
        return False
    current = now or datetime.now(UTC)
    if last is None:
        return True
    return current >= last + timedelta(minutes=normalize_minutes(minutes))


def nightly_due(
    last_full: datetime | None, hour: int, enabled: bool, now: datetime | None = None
) -> bool:
    if not enabled:
        return False
    current = now or datetime.now(UTC)
    if current.hour != normalize_hour(hour):
        return False
    if last_full is None:
        return True
    return last_full.date() < current.date()
