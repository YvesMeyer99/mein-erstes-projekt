"""ORB backtester: one opening-range-breakout trade per session day over 5-minute bars.

By default (`apply_risk_gates=True`) the backtest applies the config risk gates, so results
are less flattering than the raw strategy: the `min_reward_risk` filter (fail-closed, as in
risk.py), `max_trades_per_day`, and a latched daily + weekly loss stop. The loss caps are
resolved the way the live engine resolves them (`risk.effective_loss_caps`): a configured
cap > 0 is used, a cap of 0 falls back to the RiskConfig() defaults (3% daily / 6% weekly),
it does NOT switch the stop off. A locked day/week stays locked even if a later win lifts the
running total. Day/week buckets use `reconcile.guard_keys` on the ENTRY (trigger) time; for
the London 08:00-20:00 session that is the same UTC day as the live close-time bucket (a
session crossing UTC midnight could bucket differently). Triggers refused by a gate are
counted in `BacktestResult.skipped_by_risk` and not traded.

Because at most one trade is taken per session day, the daily-loss stop and
`max_trades_per_day` rarely bind at run level; in practice the WEEKLY loss stop and the
`min_reward_risk` filter shape the results.

NOT modelled: the spread filter (`max_spread_points`; OHLCV bars carry no spread) and
`max_open_positions` (one trade per symbol per day, so positions never overlap).
`apply_risk_gates=False` gives the raw strategy with no skipping.
"""
from collections import defaultdict
from dataclasses import dataclass

from fxbot.config import RiskConfig, SymbolConfig
from fxbot.domain import Bar, Direction, Signal
from fxbot.reconcile import guard_keys
from fxbot.risk import calculate_lot_size, effective_loss_caps
from fxbot.sessions import group_by_session_day, session_slots
from fxbot.strategy import detect_orb_trigger, plan_exit


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: list
    win_rate: float
    avg_crv: float
    max_drawdown: float
    expectancy: float
    n_trades: int
    profit_factor: float | None  # gross win / gross loss; None = no losing trades (undefined), 0.0 = no trades
    tp_hits: int
    sl_hits: int
    flat_hits: int
    skipped_by_risk: int = 0  # ORB triggers not traded because a risk gate refused them


class RiskLatch:
    """In-memory twin of the live DailyRiskGuard/WeeklyRiskGuard (no SQLite).

    A day/week locks once its booked PnL % reaches `<= -cap` and then STAYS locked even if
    later PnL recovers. Caps are the live ones (`effective_loss_caps`): a configured 0 falls
    back to the RiskConfig() defaults rather than meaning off. Also counts trades per day for
    `max_trades_per_day`.
    """

    def __init__(self, risk: RiskConfig):
        self.risk = risk
        self.daily_cap, self.weekly_cap = effective_loss_caps([risk])
        self.daily_pnl_pct: dict[str, float] = defaultdict(float)
        self.weekly_pnl_pct: dict[str, float] = defaultdict(float)
        self.locked_days: set[str] = set()
        self.locked_weeks: set[str] = set()
        self.trades_per_day: dict[str, int] = defaultdict(int)

    def is_blocked(self, day_key: str, week_key: str) -> bool:
        return (
            day_key in self.locked_days
            or week_key in self.locked_weeks
            or self.trades_per_day[day_key] >= self.risk.max_trades_per_day
        )

    def record(self, day_key: str, week_key: str, pnl_pct: float) -> None:
        self.trades_per_day[day_key] += 1
        self.daily_pnl_pct[day_key] += pnl_pct
        self.weekly_pnl_pct[week_key] += pnl_pct
        if self.daily_pnl_pct[day_key] <= -self.daily_cap:
            self.locked_days.add(day_key)
        if self.weekly_pnl_pct[week_key] <= -self.weekly_cap:
            self.locked_weeks.add(week_key)


def _profit_factor(pnls: list) -> float | None:
    """Gross win / gross loss. None (JSON null, instead of an unserializable inf)
    when there are winners but no losing trade; 0.0 when there is nothing to measure."""
    if not pnls:
        return 0.0
    gross_win = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss == 0:
        return None if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _max_drawdown(equity_curve: list) -> float:
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        dd = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _simulate_exit(signal: Signal, later_bars: list[Bar]) -> tuple[float, str]:
    """Walk bars after the trigger; return (exit_price, reason in tp/sl/flat).

    The stop is checked before the target (a bar touching both counts as the stop).
    A stop fills at the stop price even if the bar gapped through it, i.e. a full
    risk loss. With no hit, exit at the last in-session bar's close (flat-by); with
    no later bar at all, exit flat at the entry.
    """
    is_buy = signal.direction == Direction.BUY
    for bar in later_bars:
        hit_sl = bar.low <= signal.sl if is_buy else bar.high >= signal.sl
        if hit_sl:
            return signal.sl, "sl"
        hit_tp = bar.high >= signal.tp if is_buy else bar.low <= signal.tp
        if hit_tp:
            return signal.tp, "tp"
    if later_bars:
        return later_bars[-1].close, "flat"
    return signal.entry, "flat"


def run_backtest(
    bars: list[Bar],
    cfg: SymbolConfig,
    starting_balance: float = 10_000.0,
    contract_size: float = 100_000.0,
    apply_risk_gates: bool = True,
) -> BacktestResult:
    sess, strat = cfg.session, cfg.strategy
    n_slots = session_slots(sess.open, sess.flat_by)
    days = group_by_session_day(bars, sess.timezone, sess.open)

    balance = starting_balance
    equity_curve = [balance]
    trades = []
    latch = RiskLatch(cfg.risk)
    skipped_by_risk = 0

    for day in sorted(days):
        day_bars = days[day]
        trigger = detect_orb_trigger(
            day_bars, strat.or_minutes, strat.allow_short, session_slots=n_slots
        )
        if trigger is None:
            continue

        known = [day_bars[s] for s in sorted(day_bars) if s <= trigger.slot]
        signal = plan_exit(
            trigger,
            strat.stop_rule,
            strat.target_r,
            session_bars=known,
            stop_param=strat.stop_param,
        )
        day_key, week_key = guard_keys(trigger.trigger_time)
        if apply_risk_gates and (
            not (signal.crv >= cfg.risk.min_reward_risk) or latch.is_blocked(day_key, week_key)
        ):
            skipped_by_risk += 1
            continue

        balance_before = balance
        lot = calculate_lot_size(
            balance=balance,
            risk_pct=cfg.risk.risk_per_trade_pct,
            sl_distance=abs(signal.entry - signal.sl),
            contract_size=contract_size,
            volume_step=0.01,
            volume_min=0.01,
            volume_max=1_000_000_000.0,
        )

        later = [day_bars[s] for s in sorted(day_bars) if trigger.slot < s < n_slots]
        exit_price, reason = _simulate_exit(signal, later)

        price_diff = (
            exit_price - signal.entry
            if signal.direction == Direction.BUY
            else signal.entry - exit_price
        )
        pnl = price_diff * lot * contract_size
        balance += pnl
        if apply_risk_gates:
            if balance_before > 0:
                pnl_pct = pnl / balance_before * 100.0
            else:  # wiped-out account: no meaningful base, book a full loss / nothing
                pnl_pct = -100.0 if pnl < 0 else 0.0
            latch.record(day_key, week_key, pnl_pct)
        equity_curve.append(balance)
        trades.append({"pnl": pnl, "crv": signal.crv, "reason": reason})

    n_trades = len(trades)
    pnls = [t["pnl"] for t in trades]
    return BacktestResult(
        equity_curve=equity_curve,
        win_rate=sum(1 for p in pnls if p > 0) / n_trades if n_trades else 0.0,
        avg_crv=sum(t["crv"] for t in trades) / n_trades if n_trades else 0.0,
        max_drawdown=_max_drawdown(equity_curve),
        expectancy=sum(pnls) / n_trades if n_trades else 0.0,
        n_trades=n_trades,
        profit_factor=_profit_factor(pnls),
        tp_hits=sum(1 for t in trades if t["reason"] == "tp"),
        sl_hits=sum(1 for t in trades if t["reason"] == "sl"),
        flat_hits=sum(1 for t in trades if t["reason"] == "flat"),
        skipped_by_risk=skipped_by_risk,
    )
