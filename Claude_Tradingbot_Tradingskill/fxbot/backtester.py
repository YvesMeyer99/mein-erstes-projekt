"""ORB backtester: one opening-range-breakout trade per session day over 5-minute bars."""
from dataclasses import dataclass

from fxbot.config import SymbolConfig
from fxbot.domain import Bar, Direction, Signal
from fxbot.risk import calculate_lot_size
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
) -> BacktestResult:
    sess, strat = cfg.session, cfg.strategy
    n_slots = session_slots(sess.open, sess.flat_by)
    days = group_by_session_day(bars, sess.timezone, sess.open)

    balance = starting_balance
    equity_curve = [balance]
    trades = []

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
    )
