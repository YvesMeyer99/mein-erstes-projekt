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
