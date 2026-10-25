from datetime import datetime, timedelta, timezone

import pytest

from fxbot.db import init_db
from fxbot.mt5_types import ClosedDeal, SymbolInfo
from fxbot.reconcile import reconcile_closed_trades
from fxbot.risk import DailyRiskGuard, WeeklyRiskGuard
from fxbot.testing.fake_mt5_client import FakeMT5Client

UTC = timezone.utc
INFO = SymbolInfo(
    name="EURUSD", volume_step=0.01, volume_min=0.01, volume_max=100.0,
    contract_size=100_000.0, point=0.00001, digits=5,
)
ENTRY = datetime(2026, 1, 12, 8, 20, tzinfo=UTC)   # Monday
NOW = datetime(2026, 1, 12, 12, 0, tzinfo=UTC)
CLOSE = datetime(2026, 1, 12, 10, 30, tzinfo=UTC)
DAY = "2026-01-12"
WEEK = "2026-01-12"  # Monday

INSERT = (
    "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv, entry_balance, ticket) "
    "VALUES (?,?,?,?,?,?,?,?,?,?)"
)


def _setup(deals=None, max_daily=3.0, max_weekly=6.0):
    conn = init_db(":memory:")
    client = FakeMT5Client({"EURUSD": []}, balance=10_000.0, symbol_info=INFO, closed_deals=deals)
    daily = DailyRiskGuard(conn, max_daily)
    weekly = WeeklyRiskGuard(conn, max_weekly)
    return conn, client, daily, weekly


def _trade(conn, ticket=101, symbol="EURUSD", entry=ENTRY, balance=10_000.0, lot=0.5, direction="buy"):
    conn.execute(
        INSERT, (symbol, entry.isoformat(), direction, 1.1, 1.09, 1.12, lot, 2.0, balance, ticket)
    )
    conn.commit()


def _deal(position_id=101, profit=-100.0, close=CLOSE, symbol="EURUSD", volume=0.5, price=1.095):
    return ClosedDeal(position_id=position_id, symbol=symbol, profit=profit, close_time=close,
                      volume=volume, close_price=price)


def _run(conn, client, daily, weekly, now=NOW, **kw):
    return reconcile_closed_trades(client, conn, daily, weekly, now, **kw)


def test_losing_close_feeds_negative_pct_into_both_guards():
    conn, client, daily, weekly = _setup([_deal(profit=-100.0)])
    _trade(conn)
    out = _run(conn, client, daily, weekly)
    assert len(out) == 1
    assert out[0]["pnl_pct"] == pytest.approx(-1.0)
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-1.0)
    assert weekly.realized_pnl_pct(WEEK) == pytest.approx(-1.0)
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["closed"] == 1
    assert row["pnl"] == pytest.approx(-100.0)
    assert row["pnl_pct"] == pytest.approx(-1.0)
    assert row["close_price"] == pytest.approx(1.095)
    assert row["result"] == "loss"
    assert row["exit_time"] == CLOSE.isoformat()


def test_winning_close_feeds_positive_pct():
    conn, client, daily, weekly = _setup([_deal(profit=200.0, price=1.12)])
    _trade(conn)
    out = _run(conn, client, daily, weekly)
    assert out[0]["pnl_pct"] == pytest.approx(2.0)
    assert daily.realized_pnl_pct(DAY) == pytest.approx(2.0)
    assert weekly.realized_pnl_pct(WEEK) == pytest.approx(2.0)
    assert conn.execute("SELECT result FROM trades").fetchone()["result"] == "win"
    assert not daily.is_locked(DAY)


def test_uses_entry_balance_of_the_trade_not_current_balance():
    conn, client, daily, weekly = _setup([_deal(profit=-50.0)])
    client.balance = 123.0
    _trade(conn, balance=5_000.0)
    out = _run(conn, client, daily, weekly)
    assert out[0]["pnl_pct"] == pytest.approx(-1.0)


def test_enough_losses_lock_the_day():
    deals = [_deal(101, -150.0), _deal(102, -150.0, close=CLOSE + timedelta(minutes=30))]
    conn, client, daily, weekly = _setup(deals, max_daily=3.0)
    _trade(conn, 101)
    _trade(conn, 102, entry=ENTRY + timedelta(minutes=5))
    out = _run(conn, client, daily, weekly)
    assert len(out) == 2
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-3.0)
    assert daily.is_locked(DAY)
    assert not weekly.is_locked(WEEK)  # -3% of a 6% weekly cap


def test_weekly_lock_and_week_start_from_close_time():
    # close on Wednesday 2026-01-14: week starts Monday 2026-01-12, daily key is the Wednesday
    wed = datetime(2026, 1, 14, 11, 0, tzinfo=UTC)
    conn, client, daily, weekly = _setup([_deal(profit=-700.0, close=wed)], max_weekly=6.0)
    _trade(conn)
    _run(conn, client, daily, weekly, now=wed + timedelta(hours=1))
    assert daily.is_locked("2026-01-14")
    assert not daily.is_locked("2026-01-12")
    assert weekly.is_locked("2026-01-12")


def test_reconcile_is_idempotent():
    conn, client, daily, weekly = _setup([_deal(profit=-100.0)])
    _trade(conn)
    first = _run(conn, client, daily, weekly)
    second = _run(conn, client, daily, weekly)
    assert len(first) == 1 and second == []
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-1.0)
    assert weekly.realized_pnl_pct(WEEK) == pytest.approx(-1.0)


def test_open_trade_without_close_stays_open():
    conn, client, daily, weekly = _setup([])
    _trade(conn)
    assert _run(conn, client, daily, weekly) == []
    assert conn.execute("SELECT closed FROM trades").fetchone()["closed"] == 0
    assert daily.realized_pnl_pct(DAY) == 0.0
    assert not daily.is_locked(DAY)


def test_close_found_later_is_picked_up_next_run():
    conn, client, daily, weekly = _setup([])
    _trade(conn)
    assert _run(conn, client, daily, weekly) == []
    client.closed_deals.append(_deal(profit=-100.0))
    assert len(_run(conn, client, daily, weekly)) == 1
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-1.0)


def test_deal_for_other_ticket_does_not_match():
    conn, client, daily, weekly = _setup([_deal(position_id=999)])
    _trade(conn, ticket=101)
    assert _run(conn, client, daily, weekly) == []
    assert conn.execute("SELECT closed FROM trades").fetchone()["closed"] == 0


def test_ticket_match_requires_same_symbol():
    conn, client, daily, weekly = _setup([_deal(position_id=101, symbol="GBPUSD")])
    _trade(conn, ticket=101, symbol="EURUSD")
    assert _run(conn, client, daily, weekly) == []


def test_fallback_match_without_ticket_by_symbol_time_and_lot():
    conn, client, daily, weekly = _setup([_deal(position_id=555, profit=-100.0)])
    _trade(conn, ticket=None)
    out = _run(conn, client, daily, weekly)
    assert len(out) == 1
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["closed"] == 1 and row["ticket"] == 555


def test_fallback_ignores_deal_that_closed_before_entry():
    early = _deal(position_id=555, close=ENTRY - timedelta(hours=1))
    conn, client, daily, weekly = _setup([early])
    _trade(conn, ticket=None)
    assert _run(conn, client, daily, weekly) == []


def test_fallback_never_steals_a_deal_owned_by_another_trade():
    conn, client, daily, weekly = _setup([_deal(position_id=101, profit=-100.0)])
    _trade(conn, ticket=101)
    _trade(conn, ticket=None, entry=ENTRY + timedelta(minutes=1))
    out = _run(conn, client, daily, weekly)
    assert len(out) == 1  # only the ticket-owning trade closes; the legacy row stays open
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-1.0)
    # and it still does not steal it on a later run (the deal is still in the lookback window)
    assert _run(conn, client, daily, weekly) == []
    assert daily.realized_pnl_pct(DAY) == pytest.approx(-1.0)


def test_fallback_lot_mismatch_does_not_match():
    conn, client, daily, weekly = _setup([_deal(position_id=555, volume=0.2)])
    _trade(conn, ticket=None, lot=0.5)
    assert _run(conn, client, daily, weekly) == []


def test_window_covers_old_open_trade_beyond_lookback():
    old_entry = NOW - timedelta(days=10)
    old_close = old_entry + timedelta(hours=2)
    conn, client, daily, weekly = _setup([_deal(profit=-100.0, close=old_close)])
    _trade(conn, entry=old_entry)
    out = _run(conn, client, daily, weekly, lookback=timedelta(days=2))
    assert len(out) == 1


def test_deals_outside_the_window_are_not_fetched():
    stale = _deal(position_id=101, close=NOW - timedelta(days=60))
    conn, client, daily, weekly = _setup([stale])
    _trade(conn, entry=NOW - timedelta(hours=1))
    assert _run(conn, client, daily, weekly) == []


def test_missing_entry_balance_falls_back_to_current_balance():
    conn, client, daily, weekly = _setup([_deal(profit=-100.0)])
    _trade(conn, balance=None)
    out = _run(conn, client, daily, weekly)
    assert out[0]["pnl_pct"] == pytest.approx(-1.0)  # 100 / 10_000 current balance


def test_naive_now_is_rejected():
    conn, client, daily, weekly = _setup([])
    with pytest.raises(ValueError):
        _run(conn, client, daily, weekly, now=datetime(2026, 1, 12, 12, 0))


def test_latched_lock_survives_later_recovery():
    deals = [_deal(101, -400.0), _deal(102, 500.0, close=CLOSE + timedelta(minutes=30))]
    conn, client, daily, weekly = _setup(deals[:1], max_daily=3.0)
    _trade(conn, 101)
    _run(conn, client, daily, weekly)
    assert daily.is_locked(DAY)
    client.closed_deals.append(deals[1])
    _trade(conn, 102, entry=ENTRY + timedelta(minutes=5))
    _run(conn, client, daily, weekly)
    assert daily.realized_pnl_pct(DAY) == pytest.approx(1.0)
    assert daily.is_locked(DAY)  # latched
