from datetime import datetime, timezone

import pytest

from fxbot.config import RiskConfig
from fxbot.db import init_db
from fxbot.domain import Direction, Signal
from fxbot.mt5_types import Position
from fxbot.risk import (
    DailyRiskGuard,
    RiskEngine,
    WeeklyRiskGuard,
    calculate_lot_size,
    count_trades_today,
    round_down_to_volume_step,
)

UTC = timezone.utc
SIG = Signal(Direction.BUY, 1.0, entry=1.1000, sl=1.0950, tp=1.1100)  # CRV 2.0
OPEN = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
FLAT = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)
NOW = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
DATE = "2026-01-05"
WEEK = "2026-01-05"
POS_EURUSD = Position(1, "EURUSD", Direction.BUY, 0.1, 1.1, 1.09, 1.12, NOW)
POS_XAUUSD = Position(2, "XAUUSD", Direction.BUY, 0.1, 1.1, 1.09, 1.12, NOW)
INSERT_TRADE = (
    "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv) "
    "VALUES (?,?,?,?,?,?,?,?)"
)


@pytest.fixture
def conn():
    return init_db(":memory:")


@pytest.fixture
def engine(conn):
    return RiskEngine(conn, RiskConfig())


def run(engine, signal=SIG, **over):
    kw = dict(
        spread_points=10, max_spread_points=30, open_positions=[], trades_today=0,
        now_utc=NOW, session_open_utc=OPEN, session_flat_by_utc=FLAT,
        server_date=DATE, week_start=WEEK,
    )
    kw.update(over)
    return engine.check(signal, "EURUSD", **kw)


def test_lot_size_matches_ported_formula():
    assert calculate_lot_size(10_000, 1.0, 0.0050, 100_000, 0.01, 0.01, 100.0) == 0.2


def test_lot_size_clamps_and_rejects_bad_sl():
    assert calculate_lot_size(10_000, 1.0, 0.0050, 100_000, 0.01, 0.01, 0.1) == 0.1
    with pytest.raises(ValueError):
        calculate_lot_size(10_000, 1.0, 0, 100_000, 0.01, 0.01, 100.0)


def test_round_down_to_volume_step():
    assert round_down_to_volume_step(0.237, 0.01) == 0.23


def test_block_when_spread_too_wide(engine):
    d = run(engine, spread_points=40, max_spread_points=30)
    assert not d.ok and any("spread" in r for r in d.reasons)


def test_spread_equal_to_max_passes(engine):
    assert run(engine, spread_points=30, max_spread_points=30).ok


def test_block_when_position_already_open(engine):
    d = run(engine, open_positions=[POS_EURUSD])
    assert not d.ok and any("position" in r for r in d.reasons)


def test_other_symbol_position_does_not_block(engine):
    assert run(engine, open_positions=[POS_XAUUSD]).ok


def test_block_when_max_open_positions(conn):
    eng = RiskEngine(conn, RiskConfig(max_open_positions=1))
    d = run(eng, open_positions=[POS_XAUUSD])
    assert not d.ok and any("position" in r for r in d.reasons)


def test_block_when_daily_locked(conn, engine):
    DailyRiskGuard(conn, 3.0).record_pnl(DATE, -3.0)
    d = run(engine)
    assert not d.ok and any("daily" in r for r in d.reasons)


def test_block_when_weekly_locked(conn, engine):
    WeeklyRiskGuard(conn, 6.0).record_pnl(WEEK, -6.5)
    d = run(engine)
    assert not d.ok and any("weekly" in r for r in d.reasons)


def test_daily_lock_latches_after_recovery(conn, engine):
    guard = DailyRiskGuard(conn, 3.0)
    guard.record_pnl(DATE, -3.0)
    guard.record_pnl(DATE, 1.0)
    assert guard.realized_pnl_pct(DATE) == pytest.approx(-2.0)
    assert guard.is_locked(DATE)
    assert not run(engine).ok


def test_weekly_lock_latches_after_recovery(conn, engine):
    guard = WeeklyRiskGuard(conn, 6.0)
    guard.record_pnl(WEEK, -6.0)
    guard.record_pnl(WEEK, 2.0)
    assert guard.realized_pnl_pct(WEEK) == pytest.approx(-4.0)
    assert guard.is_locked(WEEK)
    assert not run(engine).ok


def test_nan_spread_blocks(engine):
    d = run(engine, spread_points=float("nan"))
    assert not d.ok and any("spread" in r for r in d.reasons)


def test_nan_crv_blocks(engine):
    from types import SimpleNamespace
    d = run(engine, signal=SimpleNamespace(crv=float("nan")))
    assert not d.ok and any("reward" in r for r in d.reasons)


def test_block_when_trades_per_day_cap(engine):
    d = run(engine, trades_today=3)
    assert not d.ok and any("trades" in r for r in d.reasons)


def test_block_when_crv_too_low(engine):
    low = Signal(Direction.BUY, 1.0, entry=1.1000, sl=1.0950, tp=1.1050)  # CRV 1.0
    d = run(engine, signal=low)
    assert not d.ok and any("reward" in r for r in d.reasons)


def test_block_outside_session(engine):
    early = datetime(2026, 1, 5, 7, 59, tzinfo=UTC)
    assert not run(engine, now_utc=early).ok
    assert not run(engine, now_utc=FLAT).ok  # end exclusive
    assert run(engine, now_utc=OPEN).ok  # start inclusive


def test_multiple_failures_give_multiple_reasons(engine):
    d = run(engine, spread_points=99, open_positions=[POS_EURUSD], trades_today=5)
    assert not d.ok and len(d.reasons) >= 3


def test_pass_on_clean_trade(engine):
    d = run(engine)
    assert d.ok and d.reasons == []


def test_count_trades_today(conn):
    conn.execute(INSERT_TRADE, ("EURUSD", "2026-01-05T08:15:00", "buy", 1.1, 1.09, 1.12, 0.1, 2.0))
    conn.execute(INSERT_TRADE, ("EURUSD", "2026-01-05T10:15:00", "buy", 1.1, 1.09, 1.12, 0.1, 2.0))
    conn.execute(INSERT_TRADE, ("XAUUSD", "2026-01-05T10:15:00", "buy", 1.1, 1.09, 1.12, 0.1, 2.0))
    conn.execute(INSERT_TRADE, ("EURUSD", "2026-01-06T08:15:00", "buy", 1.1, 1.09, 1.12, 0.1, 2.0))
    assert count_trades_today(conn, "EURUSD", "2026-01-05") == 2
