from datetime import datetime, timedelta, timezone

from fxbot.domain import Bar, Direction
from fxbot.strategy import OrbTrigger, detect_orb_trigger

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def _bar(slot, high, low, close):
    return Bar(
        time=T0 + timedelta(minutes=5 * slot),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1.0,
    )


def _range_bars():
    # 15-min range: slots 0..2 -> high 12.0, low 8.0
    return {
        0: _bar(0, 10.0, 8.0, 9.0),
        1: _bar(1, 12.0, 9.0, 11.0),
        2: _bar(2, 11.0, 8.5, 10.0),
    }


def _day(extra):
    d = _range_bars()
    d.update(extra)
    return d


BREAK_BAR_CLOSE = 12.5
DAY_WITH_UPSIDE_BREAK = _day(
    {
        3: _bar(3, 11.5, 9.5, 11.0),  # inside
        4: _bar(4, 13.0, 11.0, BREAK_BAR_CLOSE),  # close > 12.0
        5: _bar(5, 7.0, 6.0, 6.5),  # later downside, ignored
    }
)
DAY_WITH_DOWN_BREAK = _day(
    {
        3: _bar(3, 11.5, 9.5, 10.0),
        4: _bar(4, 9.0, 7.0, 7.5),  # close < 8.0
    }
)
DAY_INSIDE_RANGE = _day(
    {
        3: _bar(3, 13.0, 7.0, 10.0),  # wicks outside but closes inside
        4: _bar(4, 11.0, 9.0, 12.0),  # close == or_high is not a break
        5: _bar(5, 11.0, 9.0, 8.0),  # close == or_low is not a break
    }
)


def test_buy_trigger_on_first_close_above_range():
    t = detect_orb_trigger(DAY_WITH_UPSIDE_BREAK, or_minutes=15, allow_short=True)
    assert isinstance(t, OrbTrigger)
    assert t.direction == Direction.BUY and t.entry == BREAK_BAR_CLOSE
    assert t.slot == 4
    assert t.trigger_time == DAY_WITH_UPSIDE_BREAK[4].time
    assert (t.or_high, t.or_low) == (12.0, 8.0)


def test_sell_trigger_when_allowed():
    t = detect_orb_trigger(DAY_WITH_DOWN_BREAK, 15, allow_short=True)
    assert t.direction == Direction.SELL and t.entry == 7.5 and t.slot == 4


def test_no_short_when_disallowed_returns_none_if_only_downside():
    assert detect_orb_trigger(DAY_WITH_DOWN_BREAK, 15, allow_short=False) is None


def test_quiet_day_no_trigger_returns_none():  # Review Focus #2
    assert detect_orb_trigger(DAY_INSIDE_RANGE, 15, allow_short=True) is None


def test_missing_range_slot_returns_none():
    day = DAY_WITH_UPSIDE_BREAK.copy()
    del day[1]
    assert detect_orb_trigger(day, 15, allow_short=True) is None


def test_range_bars_themselves_never_trigger():
    # closes inside range bars may exceed earlier highs; only slots after range count
    day = {
        0: _bar(0, 10.0, 8.0, 9.0),
        1: _bar(1, 12.0, 9.0, 11.0),
        2: _bar(2, 13.0, 8.5, 12.9),  # high 13 is part of the range
    }
    assert detect_orb_trigger(day, 15, allow_short=True) is None


def test_first_side_to_fire_wins_when_short_allowed():
    day = _day(
        {
            3: _bar(3, 9.0, 7.0, 7.5),  # SELL fires first
            4: _bar(4, 14.0, 11.0, 13.5),  # later BUY
        }
    )
    assert detect_orb_trigger(day, 15, allow_short=True).direction == Direction.SELL
    # short disallowed: skip the down break and take the later BUY
    t = detect_orb_trigger(day, 15, allow_short=False)
    assert t.direction == Direction.BUY and t.slot == 4


def test_gap_in_slots_scans_in_ascending_order():
    day = _day(
        {
            9: _bar(9, 14.0, 11.0, 13.5),
            5: _bar(5, 9.0, 7.0, 7.5),
        }
    )
    assert detect_orb_trigger(day, 15, allow_short=True).slot == 5


def test_session_slots_cap_ignores_post_session_breakout():
    day = _day(
        {
            3: _bar(3, 11.5, 9.5, 10.0),  # inside
            100: _bar(100, 14.0, 11.0, 13.5),  # evening breakout, slot >= cap
        }
    )
    assert detect_orb_trigger(day, 15, allow_short=True, session_slots=96) is None
    t = detect_orb_trigger(day, 15, allow_short=True)
    assert t is not None and t.slot == 100 and t.direction == Direction.BUY


def test_session_slots_cap_is_exclusive_upper_bound():
    day = _day({95: _bar(95, 14.0, 11.0, 13.5)})
    assert detect_orb_trigger(day, 15, allow_short=True, session_slots=96).slot == 95
    assert detect_orb_trigger(day, 15, allow_short=True, session_slots=95) is None
