import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest

from fxbot.backtester import BacktestResult, run_backtest
from fxbot.config import RiskConfig, SessionConfig, StrategyConfig, SymbolConfig
from fxbot.domain import Bar

CFG_EURUSD = SymbolConfig(
    name="EURUSD",
    enabled=True,
    risk=RiskConfig(),
    session=SessionConfig(),
    strategy=StrategyConfig(),
)

# 2026-01-05 is a Monday in winter: London == UTC, session open 08:00 UTC.
OPEN = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def _bar(slot, o, h, l, c, day=OPEN):
    return Bar(time=day + timedelta(minutes=5 * slot), open=o, high=h, low=l, close=c, volume=1.0)


def _opening_range(day=OPEN):
    # OR 08:00-08:15 (slots 0..2): high 1.1010, low 1.0990 -> or_mid stop 1.1000
    return [
        _bar(0, 1.1000, 1.1010, 1.0990, 1.1000, day),
        _bar(1, 1.1000, 1.1008, 1.0992, 1.1002, day),
        _bar(2, 1.1002, 1.1009, 1.0995, 1.1005, day),
    ]


# Slot 3 closes at 1.1020 > or_high -> BUY, entry 1.1020, stop 1.1000, risk 0.0020,
# 2R target 1.1060.
_TRIGGER = _bar(3, 1.1005, 1.1022, 1.1004, 1.1020)

ONE_DAY_UP_TO_TARGET = _opening_range() + [
    _TRIGGER,
    _bar(4, 1.1020, 1.1030, 1.1015, 1.1028),
    _bar(5, 1.1028, 1.1065, 1.1025, 1.1060),  # touches 1.1060 target, never the stop
]

# Entry 1.1025 (risk 0.0025 -> exactly 0.40 lot for a 1% budget, so no lot-step
# rounding shaves the loss below the budget and the assertion is exact).
ONE_DAY_GAP_BELOW_STOP = _opening_range() + [
    _bar(3, 1.1005, 1.1027, 1.1004, 1.1025),
    # next bar opens far below the 1.1000 stop (gap): high/low all past the stop
    _bar(4, 1.0950, 1.0960, 1.0940, 1.0955),
]

ONE_QUIET_DAY = _opening_range() + [
    _bar(3, 1.1004, 1.1009, 1.0996, 1.1005),
    _bar(4, 1.1005, 1.1010, 1.0992, 1.0998),
    _bar(5, 1.0998, 1.1008, 1.0991, 1.1000),
]


def test_single_winning_day_hits_target():
    r = run_backtest(ONE_DAY_UP_TO_TARGET, CFG_EURUSD, starting_balance=10_000)
    assert isinstance(r, BacktestResult)
    assert r.n_trades == 1 and r.tp_hits == 1 and r.equity_curve[-1] > 10_000
    assert r.sl_hits == 0 and r.flat_hits == 0
    assert r.win_rate == 1.0
    assert abs(r.avg_crv - 2.0) < 1e-6


def test_gap_through_stop_is_full_risk_loss():  # Review Focus #4
    r = run_backtest(ONE_DAY_GAP_BELOW_STOP, CFG_EURUSD, starting_balance=10_000)
    assert r.sl_hits == 1
    assert (10_000 - r.equity_curve[-1]) >= 10_000 * CFG_EURUSD.risk.risk_per_trade_pct / 100 - 1e-6


def test_quiet_day_makes_no_trade():
    r = run_backtest(ONE_QUIET_DAY, CFG_EURUSD)
    assert r.n_trades == 0
    assert r.equity_curve == [10_000.0]


def test_stop_before_target_when_one_bar_touches_both():
    bars = _opening_range() + [
        _TRIGGER,
        _bar(4, 1.1020, 1.1070, 1.0990, 1.1040),  # spans both 1.1000 stop and 1.1060 target
    ]
    r = run_backtest(bars, CFG_EURUSD)
    assert r.sl_hits == 1 and r.tp_hits == 0
    assert r.equity_curve[-1] < 10_000


def test_flat_by_exit_at_last_session_bar_close():
    # 20:00 flat-by = slot 144 -> last in-session slot is 143; bars beyond are ignored
    bars = _opening_range() + [
        _TRIGGER,
        _bar(4, 1.1020, 1.1030, 1.1010, 1.1025),
        _bar(143, 1.1025, 1.1035, 1.1015, 1.1030),  # last in-session bar, close 1.1030 (+)
        _bar(144, 1.1030, 1.1100, 1.1030, 1.1090),  # post-session: would hit target, must be ignored
    ]
    r = run_backtest(bars, CFG_EURUSD)
    assert r.n_trades == 1 and r.flat_hits == 1 and r.tp_hits == 0 and r.sl_hits == 0
    assert r.equity_curve[-1] > 10_000
    assert r.win_rate == 1.0


def test_post_session_breakout_cannot_trigger():
    bars = _opening_range() + [
        _bar(3, 1.1004, 1.1009, 1.0996, 1.1005),
        _bar(144, 1.1005, 1.1030, 1.1004, 1.1020),  # breakout only after flat-by
    ]
    assert run_backtest(bars, CFG_EURUSD).n_trades == 0


def test_multiple_days_accumulate_and_metrics():
    day2 = OPEN + timedelta(days=1)
    loss_day = _opening_range(day2) + [
        _bar(3, 1.1005, 1.1022, 1.1004, 1.1020, day2),
        _bar(4, 1.1020, 1.1021, 1.0990, 1.0995, day2),
    ]
    r = run_backtest(ONE_DAY_UP_TO_TARGET + loss_day, CFG_EURUSD)
    assert r.n_trades == 2 and r.tp_hits == 1 and r.sl_hits == 1
    assert len(r.equity_curve) == 3
    assert r.win_rate == 0.5
    assert r.profit_factor > 1.0  # 2R win vs 1R loss
    assert 0.0 < r.max_drawdown < 0.05


def test_profit_factor_is_none_without_losing_trades_and_json_serializable():
    r = run_backtest(ONE_DAY_UP_TO_TARGET, CFG_EURUSD)
    assert r.n_trades == 1 and r.sl_hits == 0
    assert r.profit_factor is None  # no gross loss: undefined, not float("inf")
    assert json.loads(json.dumps(asdict(r)))["profit_factor"] is None


def test_profit_factor_is_zero_without_trades():
    assert run_backtest(ONE_QUIET_DAY, CFG_EURUSD).profit_factor == 0.0


def test_pct_stop_with_stop_param_produces_a_trade():
    # entry 1.1020, 0.2% stop -> sl 1.09980 (below the OR low), risk 0.0022, 2R target 1.1064
    cfg = replace(CFG_EURUSD, strategy=replace(CFG_EURUSD.strategy, stop_rule="pct", stop_param=0.2))
    bars = _opening_range() + [
        _TRIGGER,
        _bar(4, 1.1020, 1.1070, 1.1015, 1.1065),  # reaches the 1.1064 target, never the stop
    ]
    r = run_backtest(bars, cfg)
    assert r.n_trades == 1 and r.tp_hits == 1 and r.sl_hits == 0


def test_atr_stop_with_stop_param_produces_a_trade():
    cfg = replace(CFG_EURUSD, strategy=replace(CFG_EURUSD.strategy, stop_rule="atr", stop_param=1.0))
    quiet = [_bar(s, 1.1005, 1.1009, 1.0995, 1.1005) for s in range(3, 15)]  # slots 3..14 inside the range
    trigger = _bar(15, 1.1005, 1.1022, 1.1004, 1.1020)
    after = _bar(16, 1.1020, 1.1060, 1.1015, 1.1055)
    r = run_backtest(_opening_range() + quiet + [trigger, after], cfg)
    assert r.n_trades == 1 and r.tp_hits == 1


def test_pct_stop_without_stop_param_still_raises():
    cfg = replace(CFG_EURUSD, strategy=replace(CFG_EURUSD.strategy, stop_rule="pct"))
    with pytest.raises(ValueError, match="stop_param"):
        run_backtest(ONE_DAY_UP_TO_TARGET, cfg)


# ------------------------------------------------------------------ risk gates

def _winning_day(day):
    return _opening_range(day) + [
        _bar(3, 1.1005, 1.1022, 1.1004, 1.1020, day),
        _bar(4, 1.1020, 1.1065, 1.1015, 1.1060, day),  # 2R target hit
    ]


def _losing_day(day):
    return _opening_range(day) + [
        _bar(3, 1.1005, 1.1022, 1.1004, 1.1020, day),
        _bar(4, 1.1020, 1.1021, 1.0990, 1.0995, day),  # stop hit
    ]


def _days(n, start=OPEN):
    return [start + timedelta(days=i) for i in range(n)]


def _gated_cfg(**risk_overrides):
    return replace(CFG_EURUSD, risk=replace(CFG_EURUSD.risk, **risk_overrides))


def test_weekly_cap_skips_later_triggers_that_week():
    # Mon..Fri all lose 1%. A 1.5% weekly cap locks the week after Tuesday (-1.99%).
    mon, tue, wed, thu, fri = _days(5)
    bars = [b for d in (mon, tue, wed, thu, fri) for b in _losing_day(d)]
    cfg = _gated_cfg(max_weekly_loss_pct=1.5)

    gated = run_backtest(bars, cfg)
    assert gated.n_trades == 2 and gated.sl_hits == 2
    assert gated.skipped_by_risk == 3

    raw = run_backtest(bars, cfg, apply_risk_gates=False)
    assert raw.n_trades == 5 and raw.skipped_by_risk == 0
    assert gated.equity_curve[-1] > raw.equity_curve[-1]  # the stop saved money


def test_weekly_latch_stays_locked_after_a_later_winning_day():
    # Mon + Tue lose (week locked at -1.99% <= -1.5%). Wednesday would win +2% and lift the
    # running sum back above the cap -- but the latch must keep the week locked.
    mon, tue, wed = _days(3)
    bars = _losing_day(mon) + _losing_day(tue) + _winning_day(wed)
    cfg = _gated_cfg(max_weekly_loss_pct=1.5)

    gated = run_backtest(bars, cfg)
    assert gated.n_trades == 2 and gated.tp_hits == 0
    assert gated.skipped_by_risk == 1
    assert gated.equity_curve[-1] < 10_000

    raw = run_backtest(bars, cfg, apply_risk_gates=False)
    assert raw.n_trades == 3 and raw.tp_hits == 1


def test_new_week_unlocks_trading():
    mon, tue = _days(2)
    next_mon = OPEN + timedelta(days=7)
    bars = _losing_day(mon) + _losing_day(tue) + _winning_day(next_mon)
    r = run_backtest(bars, _gated_cfg(max_weekly_loss_pct=1.5))
    assert r.n_trades == 3 and r.tp_hits == 1 and r.skipped_by_risk == 0


def test_min_reward_risk_above_target_r_skips_every_trigger():
    bars = [b for d in _days(3) for b in _winning_day(d)]  # target_r 2.0 -> crv 2.0
    r = run_backtest(bars, _gated_cfg(min_reward_risk=2.5))
    assert r.n_trades == 0 and r.skipped_by_risk == 3
    assert r.equity_curve == [10_000.0]

    raw = run_backtest(bars, _gated_cfg(min_reward_risk=2.5), apply_risk_gates=False)
    assert raw.n_trades == 3 and raw.skipped_by_risk == 0


def test_days_without_trigger_are_not_counted_as_skipped():
    day1, day2 = _days(2)
    quiet = _opening_range(day2) + [_bar(3, 1.1004, 1.1009, 1.0996, 1.1005, day2)]
    r = run_backtest(_winning_day(day1) + quiet, _gated_cfg(min_reward_risk=2.5))
    assert r.n_trades == 0 and r.skipped_by_risk == 1


def test_daily_cap_off_when_zero_and_weekly_cap_off_when_zero():
    bars = [b for d in _days(5) for b in _losing_day(d)]
    r = run_backtest(bars, _gated_cfg(max_daily_loss_pct=0, max_weekly_loss_pct=0))
    assert r.n_trades == 5 and r.skipped_by_risk == 0


def test_default_config_does_not_trip_on_small_legacy_fixtures():
    r = run_backtest(ONE_DAY_UP_TO_TARGET, CFG_EURUSD)
    assert r.n_trades == 1 and r.skipped_by_risk == 0


def test_risk_latch_daily_cap_stays_locked_after_win():
    from fxbot.backtester import RiskLatch

    latch = RiskLatch(_gated_cfg(max_daily_loss_pct=3.0, max_weekly_loss_pct=100.0).risk)
    day, week = "2026-01-05", "2026-01-05"
    assert not latch.is_blocked(day, week)
    latch.record(day, week, -3.0)  # exactly the cap -> locked (<=)
    assert latch.is_blocked(day, week)
    latch.record(day, week, +5.0)  # running sum is now +2.0, but the latch holds
    assert latch.daily_pnl_pct[day] == pytest.approx(2.0)
    assert latch.is_blocked(day, week)
    assert not latch.is_blocked("2026-01-06", week)  # next day is free (weekly cap far away)


def test_risk_latch_max_trades_per_day():
    from fxbot.backtester import RiskLatch

    latch = RiskLatch(_gated_cfg(max_trades_per_day=2, max_daily_loss_pct=0, max_weekly_loss_pct=0).risk)
    day, week = "2026-01-05", "2026-01-05"
    latch.record(day, week, 0.5)
    assert not latch.is_blocked(day, week)
    latch.record(day, week, 0.5)
    assert latch.is_blocked(day, week)
    assert not latch.is_blocked("2026-01-06", week)
