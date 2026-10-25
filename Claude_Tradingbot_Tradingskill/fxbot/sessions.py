"""Session windows and opening range, anchored to a local timezone (default London).

Bar times are tz-aware UTC datetimes. Slotting converts to the session zone so the
session open (e.g. 08:00 London) lands on slot 0 in both BST (UTC+1) and GMT (UTC+0).
"""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from fxbot.domain import Bar

SLOT_MINUTES = 5


def _require_aware(bar_time: datetime) -> None:
    if bar_time.tzinfo is None or bar_time.utcoffset() is None:
        raise ValueError(f"bar time must be timezone-aware, got naive {bar_time!r}")


def _parse_hhmm(hhmm: str) -> time:
    hour, minute = hhmm.split(":")
    return time(int(hour), int(minute))


def session_day(bar_time: datetime, tz: str) -> date:
    """Session-local calendar date of the bar."""
    _require_aware(bar_time)
    return bar_time.astimezone(ZoneInfo(tz)).date()


def slot_index(bar_time: datetime, day: date, tz: str, open_hhmm: str) -> int | None:
    """0-based 5-minute slot since the session open on `day`; None if before the open."""
    _require_aware(bar_time)
    open_local = datetime.combine(day, _parse_hhmm(open_hhmm), tzinfo=ZoneInfo(tz))
    elapsed = bar_time.astimezone(timezone.utc) - open_local.astimezone(timezone.utc)
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 0:
        return None
    return minutes // SLOT_MINUTES


def session_slots(open_hhmm: str, flat_by_hhmm: str) -> int:
    """Number of 5-minute slots between open and flat-by (same local day)."""
    open_t = _parse_hhmm(open_hhmm)
    flat_t = _parse_hhmm(flat_by_hhmm)
    minutes = (flat_t.hour * 60 + flat_t.minute) - (open_t.hour * 60 + open_t.minute)
    return minutes // SLOT_MINUTES


def opening_range(day_bars: dict[int, Bar], or_minutes: int) -> tuple[float, float] | None:
    """(high, low) over slots 0..or_minutes/5-1; None if any of those slots is missing."""
    slots = range(or_minutes // SLOT_MINUTES)
    if not slots or any(s not in day_bars for s in slots):
        return None
    return (
        max(day_bars[s].high for s in slots),
        min(day_bars[s].low for s in slots),
    )


def group_by_session_day(
    bars: list[Bar], tz: str, open_hhmm: str
) -> dict[date, dict[int, Bar]]:
    """Group bars by session-local day, keyed by slot index; pre-open bars are skipped."""
    grouped: dict[date, dict[int, Bar]] = {}
    for bar in bars:
        day = session_day(bar.time, tz)
        slot = slot_index(bar.time, day, tz, open_hhmm)
        if slot is None:
            continue
        grouped.setdefault(day, {})[slot] = bar
    return grouped
