from datetime import datetime, timezone

import pytest

from fxbot.domain import Bar, Direction
from fxbot.mt5_types import SymbolInfo
from fxbot.testing.fake_mt5_client import FakeMT5Client

INFO = SymbolInfo(
    name="EURUSD", volume_step=0.01, volume_min=0.01, volume_max=100.0,
    contract_size=100_000.0, point=0.00001, digits=5,
)


def _bars():
    return [
        Bar(datetime(2026, 1, 1, h, tzinfo=timezone.utc), 1.1, 1.11, 1.09, 1.105, 100)
        for h in range(5)
    ]


def _client(**kw):
    return FakeMT5Client({"EURUSD": _bars()}, balance=10_000, symbol_info=INFO, **kw)


def test_send_order_records_and_opens_position():
    c = _client()
    r = c.send_order("EURUSD", Direction.BUY, 0.1, sl=1.09, tp=1.12)
    assert r.success and len(c.sent_orders) == 1
    assert c.sent_orders[0].symbol == "EURUSD"
    assert c.sent_orders[0].direction == Direction.BUY
    pos = c.get_open_positions("EURUSD")[0]
    assert pos.direction == Direction.BUY
    assert pos.ticket == r.ticket
    assert (pos.volume, pos.sl, pos.tp) == (0.1, 1.09, 1.12)


def test_close_position_removes_it():
    c = _client()
    r = c.send_order("EURUSD", Direction.SELL, 0.1, sl=1.12, tp=1.09)
    assert c.close_position(r.ticket) is True
    assert c.get_open_positions("EURUSD") == []
    assert c.close_position(r.ticket) is False


def test_partial_close_and_modify_sl():
    c = _client()
    r = c.send_order("EURUSD", Direction.BUY, 0.4, sl=1.09, tp=1.12)
    assert c.close_partial_position(r.ticket, 0.1) is True
    assert c.get_open_positions("EURUSD")[0].volume == pytest.approx(0.3)
    assert c.modify_stop_loss(r.ticket, 1.095) is True
    assert c.get_open_positions("EURUSD")[0].sl == 1.095
    assert c.modify_stop_loss(999, 1.0) is False


def test_resolve_symbol_known_and_unknown():
    c = _client()
    assert c.resolve_symbol("EURUSD") == "EURUSD"
    with pytest.raises(ValueError, match="XAUUSD"):
        c.resolve_symbol("XAUUSD")


def test_rates_and_spread_and_balance():
    c = _client(spread_points=12.0)
    assert len(c.get_rates("EURUSD", "M5", 3)) == 3
    start = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 3, tzinfo=timezone.utc)
    assert [b.time.hour for b in c.get_rates_range("EURUSD", "M5", start, end)] == [1, 2, 3]
    assert c.get_spread_points("EURUSD") == 12.0
    assert c.get_account_balance() == 10_000
    assert c.get_symbol_info("EURUSD") == INFO
    assert c.connect() and c.is_connected()
