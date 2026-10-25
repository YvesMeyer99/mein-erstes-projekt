"""ORB (opening range breakout) strategy: entry detection and exit planning."""
import math
from dataclasses import dataclass
from datetime import datetime

from fxbot.domain import Bar, Direction, Signal
from fxbot.indicators import atr14
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


_PRICE_DECIMALS = 5
_SCALE = 10**_PRICE_DECIMALS


def _round_away(price: float, direction: Direction) -> float:
    """Round a stop to 5 decimals away from entry: down for BUY, up for SELL."""
    scaled = round(price * _SCALE, 6)  # absorb float noise before floor/ceil
    fn = math.floor if direction == Direction.BUY else math.ceil
    return fn(scaled) / _SCALE


def plan_exit(
    trigger: OrbTrigger,
    stop_rule: str,
    target_r: float,
    session_bars: list[Bar] | None = None,
    stop_param: float | None = None,
) -> Signal:
    """Build a Signal from a trigger: stop by `stop_rule`, target at `target_r` x risk.

    Rules: or_mid / or_low / or_high (opening-range levels), pct (`stop_param`
    percent of entry), atr (`stop_param` x ATR14 of the `session_bars` at/before
    `trigger.trigger_time`). The stop is
    rounded away from entry. Raises ValueError for missing data, an unknown
    rule, or non-positive risk.
    """
    entry = trigger.entry
    is_buy = trigger.direction == Direction.BUY
    sign = -1.0 if is_buy else 1.0  # stop offset side relative to entry

    if stop_rule == "or_mid":
        stop = (trigger.or_high + trigger.or_low) / 2
    elif stop_rule == "or_low":
        stop = trigger.or_low
    elif stop_rule == "or_high":
        stop = trigger.or_high
    elif stop_rule == "pct":
        if stop_param is None:
            raise ValueError("stop rule 'pct' requires stop_param")
        stop = entry + sign * entry * stop_param / 100.0
    elif stop_rule == "atr":
        if stop_param is None:
            raise ValueError("stop rule 'atr' requires stop_param")
        if not session_bars:
            raise ValueError("stop rule 'atr' requires session_bars")
        # only bars at/before the trigger: later bars would be look-ahead bias
        known = [b for b in session_bars if b.time <= trigger.trigger_time]
        if not known:
            raise ValueError("stop rule 'atr' has no session_bars at/before trigger_time")
        stop = entry + sign * stop_param * atr14(known)
    else:
        raise ValueError(f"unknown stop rule: {stop_rule!r}")

    stop = _round_away(stop, trigger.direction)
    risk = (entry - stop) if is_buy else (stop - entry)
    if risk <= 0:
        raise ValueError(f"non-positive risk {risk} (entry={entry}, stop={stop})")

    target = entry - sign * target_r * risk
    return Signal(
        direction=trigger.direction,
        confidence=1.0,
        entry=entry,
        sl=stop,
        tp=target,
    )
