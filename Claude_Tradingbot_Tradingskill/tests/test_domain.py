from datetime import datetime

import pytest

from fxbot.domain import Bar, Direction, Signal


def test_buy_signal_requires_sl_below_entry_below_tp():
    with pytest.raises(ValueError):
        Signal(Direction.BUY, 1.0, entry=10, sl=11, tp=12)


def test_sell_signal_requires_tp_below_entry_below_sl():
    with pytest.raises(ValueError):
        Signal(Direction.SELL, 1.0, entry=10, sl=9, tp=8)
    sig = Signal(Direction.SELL, 1.0, entry=10, sl=11, tp=8)
    assert sig.crv == 2.0


def test_crv_is_reward_over_risk():
    assert Signal(Direction.BUY, 1.0, entry=10, sl=9, tp=12).crv == 2.0


def test_direction_values():
    assert Direction.BUY.value == "buy"
    assert Direction.SELL.value == "sell"


def test_bar_is_frozen():
    bar = Bar(datetime(2026, 1, 5, 8, 0), 1.0, 2.0, 0.5, 1.5, 100.0)
    with pytest.raises(Exception):
        bar.close = 9.0
