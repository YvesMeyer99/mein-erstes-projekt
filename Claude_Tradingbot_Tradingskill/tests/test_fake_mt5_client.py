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


def test_partial_close_float_dust_does_not_leave_phantom_position():
    c = _client()
    r = c.send_order("EURUSD", Direction.BUY, 0.4, sl=1.09, tp=1.12)
    assert c.close_partial_position(r.ticket, 0.1) is True
    assert c.close_partial_position(r.ticket, 0.3) is True
    assert c.get_open_positions("EURUSD") == []


def test_partial_close_after_float_subtraction_accepts_exact_remainder():
    c = _client()
    r = c.send_order("EURUSD", Direction.BUY, 0.3, sl=1.09, tp=1.12)
    assert c.close_partial_position(r.ticket, 0.1) is True  # 0.19999999999999998 left
    assert c.close_partial_position(r.ticket, 0.2) is True
    assert c.get_open_positions("EURUSD") == []


def test_partial_close_more_than_open_is_rejected():
    c = _client()
    r = c.send_order("EURUSD", Direction.BUY, 0.1, sl=1.09, tp=1.12)
    assert c.close_partial_position(r.ticket, 0.2) is False
    assert len(c.get_open_positions("EURUSD")) == 1


def test_resolve_symbol_matches_broker_suffix():
    info = SymbolInfo("XAUUSD.m", 0.01, 0.01, 100.0, 100.0, 0.01, 2)
    c = FakeMT5Client({"XAUUSD.m": _bars()}, balance=10_000, symbol_info=info)
    assert c.resolve_symbol("XAUUSD") == "XAUUSD.m"
    assert c.resolve_symbol("xauusd.m") == "XAUUSD.m"


def test_get_closed_deals_returns_only_deals_in_range():
    from fxbot.mt5_types import ClosedDeal

    def deal(pid, hour):
        return ClosedDeal(pid, "EURUSD", -10.0, datetime(2026, 1, 1, hour, tzinfo=timezone.utc), 0.1, 1.1)

    c = _client(closed_deals=[deal(1, 1), deal(2, 5), deal(3, 9)])
    start = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    assert [d.position_id for d in c.get_closed_deals(start, end)] == [2, 3]
    assert _client().get_closed_deals(start, end) == []
