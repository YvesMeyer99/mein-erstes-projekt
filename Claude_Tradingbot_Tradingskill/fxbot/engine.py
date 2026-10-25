"""Fully automatic live trading engine: decide -> filter -> risk -> size -> order.

There is no human confirmation anywhere on this path. The only gate in front of
`client.send_order` is `RiskEngine.check` (plus the sizing/price sanity checks
below, which can only ever block). Every non-"placed" outcome means no order
was sent.

Design notes / decisions:
  * Only CLOSED bars are used (a bar opening at t is closed once t + 5 min <= now);
    the still-forming bar returned by MT5 is dropped so a trigger is never taken
    on a half-built candle.
  * The ORB trigger is the first breakout of the day. It is only traded while it
    is fresh (on the last closed bar or the one before). A stale trigger means the
    bot was down or an earlier poll was missed; chasing it at market would enter
    far from the planned entry/stop/target, so it is skipped ("no_trigger").
  * Time Machine failure (e.g. fewer than 20 prior sessions) is NOT treated as a
    filter hit: the trade proceeds to the risk gate and the reason is recorded.
    A p_green that is NaN fails closed (filtered).
  * Positions are counted across all enabled symbols so `max_open_positions`
    is a portfolio limit, not a per-symbol one.
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fxbot.config import SymbolConfig, TradingConfig
from fxbot.domain import Signal
from fxbot.mt5_types import MT5Client, OrderResult, Position
from fxbot.risk import RiskEngine, calculate_lot_size, count_trades_today
from fxbot.sessions import SLOT_MINUTES, group_by_session_day, session_day, session_slots
from fxbot.strategy import detect_orb_trigger, plan_exit
from fxbot.timemachine import run_time_machine

log = logging.getLogger(__name__)

UTC = timezone.utc
BAR_DELTA = timedelta(minutes=SLOT_MINUTES)
BARS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 288 (worst case: a 24h market)
TODAY_BARS = BARS_PER_DAY * 2           # today's session (plus margin)
TM_LOOKBACK_DAYS = 91                   # ~65 weekdays of history for the pool
MAX_TRIGGER_AGE_BARS = 1                # trigger may be on the last or the previous closed bar


@dataclass
class TradeOutcome:
    symbol: str
    action: str  # "placed" | "blocked" | "no_trigger" | "filtered" | "flat_close"
    reasons: list[str] = field(default_factory=list)
    order: OrderResult | None = None


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _session_window_utc(sym: SymbolConfig, day: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(sym.session.timezone)
    start = datetime.combine(day, _hhmm(sym.session.open), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day, _hhmm(sym.session.flat_by), tzinfo=tz).astimezone(UTC)
    return start, end


class LiveEngine:
    def __init__(self, client: MT5Client, conn: sqlite3.Connection, cfg: TradingConfig):
        self.client = client
        self.conn = conn
        self.cfg = cfg

    # ------------------------------------------------------------------ public

    def run_all_once(self, now_utc: datetime) -> list[TradeOutcome]:
        outcomes: list[TradeOutcome] = []
        for sym in self.cfg.symbols:
            if not sym.enabled:
                continue
            try:
                outcomes.append(self.run_symbol_once(sym, now_utc))
            except Exception as exc:  # one broken symbol must not stop the others; no order is sent
                log.exception("engine error for %s", sym.name)
                outcomes.append(TradeOutcome(sym.name, "blocked", [f"error: {type(exc).__name__}: {exc}"]))
        return outcomes

    def run_symbol_once(self, sym: SymbolConfig, now_utc: datetime) -> TradeOutcome:
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            raise ValueError(f"now_utc must be timezone-aware, got naive {now_utc!r}")
        now_utc = now_utc.astimezone(UTC)

        client = self.client
        resolved = client.resolve_symbol(sym.name)
        today = session_day(now_utc, sym.session.timezone)
        open_utc, flat_utc = _session_window_utc(sym, today)

        # 1. flat-by: close what is open, never open anything new
        if now_utc >= flat_utc:
            return self._flat_close(sym, resolved, now_utc)

        # 2. closed bars only
        n_slots = session_slots(sym.session.open, sym.session.flat_by)
        tm = self.cfg.timemachine
        count = BARS_PER_DAY * TM_LOOKBACK_DAYS if tm.enabled else TODAY_BARS
        raw = client.get_rates(resolved, self.cfg.timeframe, count)
        bars = [b for b in raw if b.time + BAR_DELTA <= now_utc]

        # 3. today's ORB trigger
        days = group_by_session_day(bars, sym.session.timezone, sym.session.open)
        day_bars = days.get(today)
        if not day_bars:
            return TradeOutcome(sym.name, "no_trigger", ["no closed bars for today's session yet"])
        strat = sym.strategy
        trigger = detect_orb_trigger(
            day_bars, strat.or_minutes, strat.allow_short, session_slots=n_slots
        )
        if trigger is None:
            return TradeOutcome(sym.name, "no_trigger", ["no opening-range breakout yet"])
        age = max(day_bars) - trigger.slot
        if age > MAX_TRIGGER_AGE_BARS:
            return TradeOutcome(
                sym.name, "no_trigger",
                [f"stale trigger: breakout at {trigger.trigger_time.isoformat()} is {age} bars old"],
            )

        # 4. exit plan
        known = [day_bars[s] for s in sorted(day_bars) if s <= trigger.slot]
        try:
            signal = plan_exit(
                trigger, strat.stop_rule, strat.target_r,
                session_bars=known, stop_param=getattr(strat, "stop_param", None),
            )
        except ValueError as exc:
            return TradeOutcome(sym.name, "blocked", [f"cannot plan exit: {exc}"])

        # 5. optional Time Machine filter
        notes: list[str] = []
        if tm.enabled:
            try:
                result = run_time_machine(
                    bars, today, trigger, signal, sym, replays=tm.replays, seed=tm.seed
                )
            except ValueError as exc:
                notes.append(f"time machine unavailable, trade not filtered: {exc}")
            else:
                p_green = result["p_green"]
                if not (p_green >= tm.min_p_green):  # NaN fails closed
                    return TradeOutcome(
                        sym.name, "filtered",
                        [f"time machine p_green {p_green} < min_p_green {tm.min_p_green}"],
                    )

        # 6. hard risk gate
        server_date = now_utc.date().isoformat()
        week_start = (now_utc.date() - timedelta(days=now_utc.weekday())).isoformat()
        open_positions = self._all_open_positions(resolved)
        decision = RiskEngine(self.conn, sym.risk).check(
            signal,
            resolved,
            spread_points=client.get_spread_points(resolved),
            max_spread_points=strat.max_spread_points,
            open_positions=open_positions,
            trades_today=count_trades_today(self.conn, resolved, server_date),
            now_utc=now_utc,
            session_open_utc=open_utc,
            session_flat_by_utc=flat_utc,
            server_date=server_date,
            week_start=week_start,
        )
        if not decision.ok:
            return TradeOutcome(sym.name, "blocked", list(decision.reasons))

        # 7. price sanity: market must still be inside the planned stop/target corridor
        bid, ask = client.get_current_price(resolved)
        price = ask if signal.direction.value == "buy" else bid
        lo, hi = sorted((signal.sl, signal.tp))
        if not (lo < price < hi):
            return TradeOutcome(
                sym.name, "blocked",
                [f"market price {price} outside planned stop/target range ({lo}, {hi})"],
            )

        # 8. size
        balance = client.get_account_balance()
        info = client.get_symbol_info(resolved)
        sl_distance = abs(signal.entry - signal.sl)
        risk_pct = sym.risk.risk_per_trade_pct
        lot = calculate_lot_size(
            balance, risk_pct, sl_distance,
            info.contract_size, info.volume_step, info.volume_min, info.volume_max,
        )
        budget = balance * risk_pct / 100.0
        # the helper clamps up to volume_min / max(...); never risk more than the budget
        if not (balance > 0 and lot * sl_distance * info.contract_size <= budget * (1 + 1e-9)):
            return TradeOutcome(
                sym.name, "blocked",
                [f"lot {lot} would risk more than {risk_pct}% of balance {balance}"],
            )

        # 9. order (only reachable after RiskEngine PASS)
        order = client.send_order(resolved, signal.direction, lot, signal.sl, signal.tp)
        if not order.success:
            return TradeOutcome(sym.name, "blocked", [f"order rejected: {order.comment}"], order)
        self._record_trade(resolved, now_utc, signal, lot, balance, notes)
        return TradeOutcome(sym.name, "placed", notes, order)

    # ----------------------------------------------------------------- helpers

    def _all_open_positions(self, resolved: str) -> list[Position]:
        """Open positions across all enabled symbols (portfolio-wide max_open_positions)."""
        positions = list(self.client.get_open_positions(resolved))
        seen = {resolved}
        for other in self.cfg.symbols:
            if not other.enabled:
                continue
            try:
                name = self.client.resolve_symbol(other.name)
            except ValueError:
                continue
            if name in seen:
                continue
            seen.add(name)
            positions.extend(self.client.get_open_positions(name))
        return positions

    def _flat_close(self, sym: SymbolConfig, resolved: str, now_utc: datetime) -> TradeOutcome:
        positions = self.client.get_open_positions(resolved)
        if not positions:
            return TradeOutcome(sym.name, "no_trigger", ["at/after flat-by; no open position"])
        failed = [p.ticket for p in positions if not self.client.close_position(p.ticket)]
        if failed:
            return TradeOutcome(
                sym.name, "blocked", [f"flat-by close failed for ticket(s) {failed}"]
            )
        return TradeOutcome(
            sym.name, "flat_close", [f"closed {len(positions)} position(s) at flat-by"]
        )

    def _record_trade(
        self, resolved: str, now_utc: datetime, signal: Signal, lot: float,
        balance: float, notes: list[str],
    ) -> None:
        try:
            self.conn.execute(
                "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv, entry_balance) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (resolved, now_utc.isoformat(), signal.direction.value, signal.entry,
                 signal.sl, signal.tp, lot, signal.crv, balance),
            )
            self.conn.commit()
        except sqlite3.Error as exc:  # the order is already live; surface, don't raise
            log.exception("failed to record trade for %s", resolved)
            notes.append(f"order placed but trade row not recorded: {exc}")
