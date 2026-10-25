"""ORB (opening range breakout) strategy: entry detection."""
from dataclasses import dataclass
from datetime import datetime

from fxbot.domain import Bar, Direction
from fxbot.sessions import SLOT_MINUTES, opening_range


@dataclass(frozen=True)
class OrbTrigger:
    direction: Direction
    entry: float
    trigger_time: datetime
    slot: int
    or_high: float
    or_low: float


def detect_orb_trigger(
    day_bars: dict[int, Bar],
    or_minutes: int,
    allow_short: bool,
    session_slots: int | None = None,
) -> OrbTrigger | None:
    """First bar after the opening range whose close breaks it.

    BUY when close > or_high, SELL (only if allow_short) when close < or_low.
    If `session_slots` is given, slots >= session_slots (post-session bars) are
    ignored. Returns None if the range is incomplete or no bar fires.
    """
    rng = opening_range(day_bars, or_minutes)
    if rng is None:
        return None
    or_high, or_low = rng
    first_slot = or_minutes // SLOT_MINUTES

    for slot in sorted(day_bars):
        if slot < first_slot:
            continue
        if session_slots is not None and slot >= session_slots:
            break
        bar = day_bars[slot]
        if bar.close > or_high:
            direction = Direction.BUY
        elif allow_short and bar.close < or_low:
            direction = Direction.SELL
        else:
            continue
        return OrbTrigger(
            direction=direction,
            entry=bar.close,
            trigger_time=bar.time,
            slot=slot,
            or_high=or_high,
            or_low=or_low,
        )
    return None
