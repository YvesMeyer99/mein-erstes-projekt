from datetime import datetime, timedelta, timezone

import pytest

from fxbot.domain import Bar, Direction
from fxbot.indicators import atr14
from fxbot.strategy import OrbTrigger, plan_exit

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def _trigger(direction, entry, or_high=1.11, or_low=1.10):
    return OrbTrigger(
        direction=direction,
        entry=entry,
        trigger_time=T0,
        slot=3,
        or_high=or_high,
        or_low=or_low,
    )


BUY_TRIGGER = _trigger(Direction.BUY, 1.111)
SELL_TRIGGER = _trigger(Direction.SELL, 1.099)


def _bars(n, rng=0.002, base=1.10):
    return [
        Bar(
            time=T0 + timedelta(minutes=5 * i),
            open=base,
            high=base + rng / 2,
            low=base - rng / 2,
            close=base,
            volume=1.0,
        )
        for i in range(n)
    ]


def test_or_mid_stop_and_2r_target_for_buy():
    s = plan_exit(BUY_TRIGGER, "or_mid", 2.0)
    assert s.direction == Direction.BUY
    assert s.sl == 1.105
    assert round(s.tp, 3) == round(1.111 + 2 * (1.111 - 1.105), 3)
    assert s.confidence == 1.0


def test_sell_uses_or_high_stop_above_entry():
    s = plan_exit(SELL_TRIGGER, "or_high", 2.0)
    assert s.sl > s.entry > s.tp
    assert s.sl == 1.11
    assert round(s.tp, 4) == round(1.099 - 2 * (1.11 - 1.099), 4)


def test_buy_or_low_stop():
    s = plan_exit(BUY_TRIGGER, "or_low", 1.0)
    assert s.sl == 1.10
    assert s.crv == pytest.approx(1.0)


def test_pct_stop_rounds_away_from_entry():
    buy = plan_exit(_trigger(Direction.BUY, 1.11111), "pct", 2.0, stop_param=0.1)
    # raw stop 1.11111 * 0.999 = 1.1099988900 -> floor to 5dp
    assert buy.sl == 1.10999
    sell = plan_exit(_trigger(Direction.SELL, 1.11111), "pct", 2.0, stop_param=0.1)
    # raw stop 1.11111 * 1.001 = 1.1122211100 -> ceil to 5dp
    assert sell.sl == 1.11223


def test_atr_stop_uses_param_times_atr():
    bars = _bars(20, rng=0.002)
    assert atr14(bars) == pytest.approx(0.002)
    s = plan_exit(BUY_TRIGGER, "atr", 2.0, session_bars=bars, stop_param=1.5)
    assert s.sl == pytest.approx(1.111 - 0.003, abs=1e-9)
    assert s.tp == pytest.approx(1.111 + 0.006, abs=1e-9)


def test_atr_stop_requires_session_bars():
    with pytest.raises(ValueError):
        plan_exit(BUY_TRIGGER, "atr", 2.0, stop_param=1.5)


def test_atr_and_pct_require_stop_param():
    with pytest.raises(ValueError):
        plan_exit(BUY_TRIGGER, "atr", 2.0, session_bars=_bars(20))
    with pytest.raises(ValueError):
        plan_exit(BUY_TRIGGER, "pct", 2.0)


def test_unknown_stop_rule_raises():
    with pytest.raises(ValueError):
        plan_exit(BUY_TRIGGER, "bogus", 2.0)


def test_zero_or_negative_risk_raises():
    # entry equals the or_low stop -> risk 0
    with pytest.raises(ValueError):
        plan_exit(_trigger(Direction.BUY, 1.10), "or_low", 2.0)
    # stop on the wrong side of entry -> negative risk
    with pytest.raises(ValueError):
        plan_exit(_trigger(Direction.BUY, 1.099), "or_low", 2.0)


def test_atr14_true_range_uses_prior_close_gap():
    bars = _bars(15, rng=0.002)
    # last bar gaps up: prev close 1.10, high 1.12, low 1.115 -> TR = 0.02
    bars[-1] = Bar(T0 + timedelta(minutes=75), 1.115, 1.12, 1.115, 1.118, 1.0)
    expected = (13 * 0.002 + 0.02) / 14
    assert atr14(bars) == pytest.approx(expected)


def test_atr14_needs_enough_bars():
    with pytest.raises(ValueError):
        atr14(_bars(14))
