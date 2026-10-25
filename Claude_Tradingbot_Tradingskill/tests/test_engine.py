import random
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from fxbot.config import (
    RiskConfig, SessionConfig, StrategyConfig, SymbolConfig, TMConfig, TradingConfig,
)
from fxbot.db import init_db
from fxbot.domain import Bar, Direction
from fxbot.engine import LiveEngine, TradeOutcome
from fxbot.mt5_types import SymbolInfo
from fxbot.testing.fake_mt5_client import FakeMT5Client

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
INFO = SymbolInfo(
    name="EURUSD", volume_step=0.01, volume_min=0.01, volume_max=100.0,
    contract_size=100_000.0, point=0.00001, digits=5,
)
TODAY = date(2026, 1, 12)  # Monday, winter: London == UTC
OPEN = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)
NOW_AFTER_BREAK = datetime(2026, 1, 12, 8, 20, tzinfo=UTC)  # slot 3 (08:15) just closed
NOW_FORMING = datetime(2026, 1, 12, 8, 22, tzinfo=UTC)      # slot 4 still forming
NOW_AT_FLAT_BY = datetime(2026, 1, 12, 20, 0, tzinfo=UTC)


def _bar(t: datetime, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0)


def _slot_time(slot: int, day_open: datetime = OPEN) -> datetime:
    return day_open + timedelta(minutes=5 * slot)


def _today_bars(closes: list[float]) -> list[Bar]:
    """Slots 0..2 form the opening range (high 1.1010, low 1.1000); slot 3+ from `closes`."""
    bars = [_bar(_slot_time(s), 1.1005, 1.1010, 1.1000, 1.1005) for s in range(3)]
    for i, c in enumerate(closes):
        bars.append(_bar(_slot_time(3 + i), 1.1005, max(c, 1.1010), min(c, 1.1000), c))
    return bars


def _history(days: int, n_slots: int = 144, seed: int = 7) -> list[Bar]:
    rng = random.Random(seed)
    out: list[Bar] = []
    d, produced = TODAY, 0
    while produced < days:
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        day_open = datetime(d.year, d.month, d.day, 8, 0, tzinfo=LONDON).astimezone(UTC)
        prev = 1.10
        for s in range(n_slots):
            c = prev * (1 + rng.uniform(-0.0006, 0.0006))
            h = max(prev, c) * (1 + rng.uniform(0, 0.0003))
            l = min(prev, c) * (1 - rng.uniform(0, 0.0003))
            out.append(_bar(_slot_time(s, day_open), prev, h, l, c))
            prev = c
        produced += 1
    return sorted(out, key=lambda b: b.time)


def _symbol_cfg(max_spread: float = 30.0, **strategy) -> SymbolConfig:
    return SymbolConfig(
        name="EURUSD", enabled=True, risk=RiskConfig(),
        session=SessionConfig(timezone="Europe/London", open="08:00", flat_by="20:00"),
        strategy=StrategyConfig(
            or_minutes=15, stop_rule="or_mid", target_r=2.0, allow_short=True,
            max_spread_points=max_spread, **strategy,
        ),
    )


def _trading_cfg(sym: SymbolConfig, tm: TMConfig | None = None) -> TradingConfig:
    return TradingConfig(timeframe="M5", timemachine=tm or TMConfig(enabled=False), symbols=[sym])


def _make(bars: list[Bar], sym: SymbolConfig | None = None, tm: TMConfig | None = None,
          spread: float = 5.0, balance: float = 10_000.0):
    sym = sym or _symbol_cfg()
    client = FakeMT5Client({"EURUSD": bars}, balance=balance, symbol_info=INFO, spread_points=spread,
                          server_time=NOW_AFTER_BREAK)
    conn = init_db(":memory:")
    return LiveEngine(client, conn, _trading_cfg(sym, tm)), client, conn, sym


BREAKOUT = _today_bars([1.1020])


def test_places_order_on_clean_breakout():
    engine, client, conn, sym = _make(BREAKOUT)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert isinstance(out, TradeOutcome)
    assert out.action == "placed", out.reasons
    assert out.order is not None and out.order.success
    sent = client.sent_orders[-1]
    assert sent.symbol == "EURUSD" and sent.direction == Direction.BUY
    assert sent.sl == pytest.approx(1.1005) and sent.tp == pytest.approx(1.1050)
    assert sent.lot == pytest.approx(0.65)  # 1% of 10k over live risk 0.001525 (ask = 1.1020 + half the 5pt spread)
    row = conn.execute("SELECT * FROM trades").fetchall()
    assert len(row) == 1
    assert row[0]["symbol"] == "EURUSD" and row[0]["direction"] == "buy"
    assert row[0]["lot"] == pytest.approx(0.65)
    assert row[0]["entry_price"] == pytest.approx(1.1020)


def test_second_call_same_day_places_nothing_more():
    engine, client, _, sym = _make(BREAKOUT)
    assert engine.run_symbol_once(sym, NOW_AFTER_BREAK).action == "placed"
    again = engine.run_symbol_once(sym, NOW_AFTER_BREAK + timedelta(minutes=5))
    assert again.action == "blocked"
    assert len(client.sent_orders) == 1


def test_no_trigger_places_nothing():
    engine, client, _, sym = _make(_today_bars([1.1008]))  # inside the range
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "no_trigger" and out.order is None
    assert client.sent_orders == []


def test_no_bars_today_is_no_trigger():
    engine, client, _, sym = _make(_history(3))
    out = engine.run_symbol_once(sym, datetime(2026, 1, 12, 8, 2, tzinfo=UTC))
    assert out.action == "no_trigger"
    assert client.sent_orders == []


def test_forming_bar_is_ignored():
    # slot 3 closed (no breakout); slot 4 is still forming and already above the range
    bars = _today_bars([1.1008, 1.1030])
    engine, client, _, sym = _make(bars)
    out = engine.run_symbol_once(sym, NOW_FORMING)
    assert out.action == "no_trigger"
    assert client.sent_orders == []


def test_stale_trigger_is_not_traded():
    # breakout was at slot 3; by 09:00 it is far in the past -> do not chase it
    bars = _today_bars([1.1020] + [1.1021] * 8)
    engine, client, _, sym = _make(bars)
    out = engine.run_symbol_once(sym, datetime(2026, 1, 12, 9, 0, tzinfo=UTC))
    assert out.action == "no_trigger"
    assert any("stale" in r for r in out.reasons)
    assert client.sent_orders == []


def test_post_session_bars_cannot_trigger():
    # range never broken inside the session; a breakout bar exists only after flat-by
    bars = _today_bars([1.1008] * 141)  # fills slots 3..143
    bars.append(_bar(_slot_time(144), 1.1005, 1.1030, 1.1000, 1.1030))
    engine, client, _, sym = _make(bars)
    out = engine.run_symbol_once(sym, datetime(2026, 1, 12, 20, 6, tzinfo=UTC))
    assert out.action == "no_trigger"
    assert client.sent_orders == []


def test_risk_block_wide_spread_places_nothing():
    engine, client, _, sym = _make(BREAKOUT, sym=_symbol_cfg(max_spread=10.0), spread=50.0)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert any("spread" in r for r in out.reasons)
    assert client.sent_orders == []


def test_risk_block_low_reward_risk_places_nothing():
    sym = replace(_symbol_cfg(), strategy=replace(_symbol_cfg().strategy, target_r=1.0))
    engine, client, _, sym = _make(BREAKOUT, sym=sym)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert client.sent_orders == []


def test_risk_block_locked_day_places_nothing():
    engine, client, conn, sym = _make(BREAKOUT)
    conn.execute("INSERT INTO daily_risk (date, realized_pnl_pct, is_locked) VALUES ('2026-01-12', -3.5, 1)")
    conn.commit()
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert client.sent_orders == []


def test_min_lot_above_risk_budget_is_blocked():
    # tiny balance: even the minimum lot would risk far more than 1%
    engine, client, _, sym = _make(BREAKOUT, balance=100.0)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert client.sent_orders == []


def test_price_already_past_target_is_blocked():
    bars = _today_bars([1.1020])
    bars[-1] = replace(bars[-1], close=1.1020)
    engine, client, _, sym = _make(bars)
    client.get_current_price = lambda symbol: (1.1060, 1.1061)  # ran through the TP
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert client.sent_orders == []


def test_lot_is_sized_on_live_price_not_planned_entry():
    engine, client, _, sym = _make(BREAKOUT)
    client.get_current_price = lambda symbol: (1.1021, 1.1022)  # ask drifted 2 pips toward TP
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "placed", out.reasons
    # live risk 0.0017 -> 100 / 170 = 0.588 -> 0.58 (planned-entry sizing would give 0.66)
    assert client.sent_orders[-1].lot == pytest.approx(0.58)


def test_drift_that_ruins_live_reward_risk_is_blocked():
    engine, client, _, sym = _make(BREAKOUT)
    client.get_current_price = lambda symbol: (1.1029, 1.1030)  # live RR 0.8 < 1.5
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked"
    assert any("live reward/risk" in r for r in out.reasons)
    assert client.sent_orders == []


class _InsertFailsConn:
    """sqlite connection proxy whose trades INSERT fails."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *a):
        if sql.lstrip().upper().startswith("INSERT INTO TRADES"):
            raise sqlite3.OperationalError("disk I/O error")
        return self._conn.execute(sql, *a)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_failed_trade_row_latches_symbol_for_the_day():
    engine, client, conn, sym = _make(BREAKOUT)
    engine.conn = _InsertFailsConn(conn)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "placed" and any("not recorded" in r for r in out.reasons)
    for pos in client.get_open_positions("EURUSD"):  # position gone (e.g. SL hit): only the latch is left
        client.close_position(pos.ticket)
    again = engine.run_symbol_once(sym, NOW_AFTER_BREAK + timedelta(minutes=5))
    assert again.action == "blocked" and any("already attempted" in r for r in again.reasons)
    assert len(client.sent_orders) == 1


def test_send_order_raising_latches_symbol_for_the_day():
    engine, client, _, sym = _make(BREAKOUT)
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("connection lost after accept")

    client.send_order = boom
    with pytest.raises(RuntimeError):
        engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    again = engine.run_symbol_once(sym, NOW_AFTER_BREAK + timedelta(minutes=5))
    assert again.action == "blocked"
    assert len(calls) == 1


def test_next_day_is_not_latched():
    engine, _, _, sym = _make(BREAKOUT)
    engine._attempted.add(("EURUSD", date(2026, 1, 9)))
    assert engine.run_symbol_once(sym, NOW_AFTER_BREAK).action == "placed"


def test_rejected_order_is_reported_not_recorded():
    from fxbot.mt5_types import OrderResult
    engine, client, conn, sym = _make(BREAKOUT)
    client.send_order = lambda *a, **k: OrderResult(False, None, "no money")
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "blocked" and out.order is not None and not out.order.success
    assert conn.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"] == 0


def test_timemachine_filter_drops_bad_odds():
    bars = _history(25) + BREAKOUT
    tm = TMConfig(enabled=True, min_p_green=1.01, replays=200, seed=19)  # p_green can never reach it
    engine, client, _, sym = _make(bars, tm=tm)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "filtered"
    assert client.sent_orders == []


def test_timemachine_filter_passes_good_odds():
    bars = _history(25) + BREAKOUT
    tm = TMConfig(enabled=True, min_p_green=0.0, replays=200, seed=19)
    engine, client, _, sym = _make(bars, tm=tm)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "placed", out.reasons
    assert len(client.sent_orders) == 1


def test_timemachine_with_too_little_history_fails_closed():
    bars = _history(3) + BREAKOUT  # < 20 sessions -> run_time_machine raises
    tm = TMConfig(enabled=True, min_p_green=0.0, replays=200, seed=19)  # even a 0.0 bar must not pass
    engine, client, _, sym = _make(bars, tm=tm)
    out = engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    assert out.action == "filtered"
    assert any("time machine" in r.lower() for r in out.reasons)
    assert client.sent_orders == []


def test_timemachine_unexpected_error_propagates():
    bars = _history(25) + BREAKOUT
    tm = TMConfig(enabled=True, min_p_green=0.0, replays=200, seed=19)
    engine, client, _, sym = _make(bars, tm=tm)
    import fxbot.engine as eng
    orig = eng.run_time_machine
    eng.run_time_machine = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
    try:
        with pytest.raises(KeyError):
            engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    finally:
        eng.run_time_machine = orig
    assert client.sent_orders == []


def test_flat_by_closes_open_position():
    engine, client, _, sym = _make(BREAKOUT)
    assert engine.run_symbol_once(sym, NOW_AFTER_BREAK).action == "placed"
    assert len(client.get_open_positions("EURUSD")) == 1
    out = engine.run_symbol_once(sym, NOW_AT_FLAT_BY)
    assert out.action == "flat_close"
    assert client.get_open_positions("EURUSD") == []


@pytest.mark.parametrize("now", [
    datetime(2026, 1, 12, 7, 30, tzinfo=UTC),   # pre-open today
    datetime(2026, 1, 12, 12, 0, tzinfo=UTC),   # mid-session today
])
def test_position_from_yesterday_is_closed(now):
    engine, client, _, sym = _make(BREAKOUT)
    client.server_time = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)  # opened on an earlier session day
    client.send_order("EURUSD", Direction.BUY, 0.1, 1.09, 1.12)
    out = engine.run_symbol_once(sym, now)
    assert out.action == "flat_close"
    assert client.get_open_positions("EURUSD") == []


def test_position_before_open_today_is_closed_even_if_opened_today():
    engine, client, _, sym = _make(BREAKOUT)
    client.server_time = datetime(2026, 1, 12, 7, 0, tzinfo=UTC)
    client.send_order("EURUSD", Direction.BUY, 0.1, 1.09, 1.12)
    out = engine.run_symbol_once(sym, datetime(2026, 1, 12, 7, 30, tzinfo=UTC))
    assert out.action == "flat_close"


def test_before_flat_by_open_position_is_left_alone():
    engine, client, _, sym = _make(BREAKOUT)
    engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    out = engine.run_symbol_once(sym, datetime(2026, 1, 12, 19, 55, tzinfo=UTC))
    assert out.action != "flat_close"
    assert len(client.get_open_positions("EURUSD")) == 1


def test_after_flat_by_without_position_places_nothing():
    engine, client, _, sym = _make(BREAKOUT)
    out = engine.run_symbol_once(sym, NOW_AT_FLAT_BY)
    assert out.action == "no_trigger"
    assert client.sent_orders == []


def test_flat_close_failure_is_reported():
    engine, client, _, sym = _make(BREAKOUT)
    engine.run_symbol_once(sym, NOW_AFTER_BREAK)
    client.close_position = lambda ticket: False
    out = engine.run_symbol_once(sym, NOW_AT_FLAT_BY)
    assert out.action == "blocked"
    assert any("close failed" in r for r in out.reasons)


def test_naive_now_is_rejected():
    engine, _, _, sym = _make(BREAKOUT)
    with pytest.raises(ValueError):
        engine.run_symbol_once(sym, datetime(2026, 1, 12, 8, 20))


def test_run_all_once_covers_enabled_symbols_only():
    sym = _symbol_cfg()
    disabled = replace(sym, name="GBPUSD", enabled=False)
    cfg = TradingConfig(timeframe="M5", timemachine=TMConfig(), symbols=[sym, disabled])
    client = FakeMT5Client({"EURUSD": BREAKOUT}, balance=10_000.0, symbol_info=INFO, spread_points=5.0)
    engine = LiveEngine(client, init_db(":memory:"), cfg)
    outs = engine.run_all_once(NOW_AFTER_BREAK)
    assert [o.symbol for o in outs] == ["EURUSD"]
    assert outs[0].action == "placed"


def test_run_all_once_isolates_symbol_errors():
    sym = _symbol_cfg()
    broken = replace(sym, name="XAUUSD")  # not available at the (fake) broker
    cfg = TradingConfig(timeframe="M5", timemachine=TMConfig(), symbols=[broken, sym])
    client = FakeMT5Client({"EURUSD": BREAKOUT}, balance=10_000.0, symbol_info=INFO, spread_points=5.0)
    engine = LiveEngine(client, init_db(":memory:"), cfg)
    outs = engine.run_all_once(NOW_AFTER_BREAK)
    assert [(o.symbol, o.action) for o in outs] == [("XAUUSD", "blocked"), ("EURUSD", "placed")]
    assert any("error" in r for r in outs[0].reasons)
