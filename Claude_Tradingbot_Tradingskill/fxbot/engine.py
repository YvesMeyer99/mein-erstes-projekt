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
  * Time Machine fails CLOSED: with the filter enabled, a ValueError from
    run_time_machine (e.g. fewer than 20 prior sessions) or a NaN p_green means
    "filtered" - no order. Other exception types propagate.
  * An in-memory per-(symbol, session-day) "attempted" latch is set right before
    send_order, so a failed trades-row write or an exception after the broker
    accepted the order can never produce a second order the same day. A clean
    `success=False` result (nothing was placed, e.g. a requote) releases the latch
    again so a transient rejection does not forfeit the symbol for the day; an
    exception or a successful placement keeps it. (Lost on process restart; the
    open-position check is then the remaining guard.)
  * Sizing and the reward:risk check use the LIVE fill price (ask/bid), not the
    trigger-bar close.
  * Positions that should already be flat (after flat-by, before the open, or
    opened on an earlier session day) are closed first.
  * Positions are counted across all enabled symbols so `max_open_positions`
    is a portfolio limit, not a per-symbol one.
  * Closed trades are reconciled at the START of every `run_all_once` (before any
    entry logic): realized P&L from the broker's deal history is fed into the daily
    and weekly guards, so a loss limit tripped by a stop-out blocks new entries in
    that same pass. The guards are conn-backed, so the RiskEngine sees the lock
    through the shared DB. A trades row that is still open after reconciliation although
    its session is over (or it is older than STALE_HOURS) AND whose ticket is not held at
    the broker means a close was never matched: the loss totals may be understated, so
    it is logged loudly on every pass and new entries are blocked (flat-by closes still
    run) until the row reconciles. The reconciliation guards use the STRICTEST loss caps of
    the enabled symbols (the lock is portfolio-wide). If reconciliation itself fails,
    new entries are blocked for that pass (fail closed); flat-by closes still run.
"""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fxbot.config import RiskConfig, SymbolConfig, TradingConfig
from fxbot.domain import Direction, Signal
from fxbot.mt5_types import MT5Client, OrderResult, Position
from fxbot.reconcile import reconcile_closed_trades
from fxbot.risk import (
    DailyRiskGuard, RiskEngine, WeeklyRiskGuard, calculate_lot_size, count_trades_today,
)
from fxbot.sessions import SLOT_MINUTES, group_by_session_day, session_day, session_slots
from fxbot.strategy import detect_orb_trigger, plan_exit
from fxbot.timemachine import run_time_machine

log = logging.getLogger(__name__)

UTC = timezone.utc
BAR_DELTA = timedelta(minutes=SLOT_MINUTES)
BARS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 288 (worst case: a 24h market)
TODAY_BARS = BARS_PER_DAY * 2           # today's session (plus margin)
TM_LOOKBACK_DAYS = 91                   # ~65 weekdays of history for the pool
STALE_HOURS = 24                        # an open row older than this is stale even without a session end
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
        self._attempted: set[tuple[str, date]] = set()
        daily_cap, weekly_cap = self._strictest_loss_caps(cfg)
        self.daily_guard = DailyRiskGuard(conn, daily_cap)
        self.weekly_guard = WeeklyRiskGuard(conn, weekly_cap)
        self.last_reconciled: list[dict] = []
        self._reconcile_ok = True
        self.stale_unmatched: list[dict] = []

    @staticmethod
    def _strictest_loss_caps(cfg: TradingConfig) -> tuple[float, float]:
        """Smallest positive daily/weekly loss cap among enabled symbols (a cap of 0 means
        "off" for the config check, so it is ignored); RiskConfig defaults if none is set."""
        enabled = [s.risk for s in cfg.symbols if s.enabled]
        default = RiskConfig()

        def strictest(values: list[float], fallback: float) -> float:
            positive = [v for v in values if v > 0]
            return min(positive) if positive else fallback

        return (
            strictest([r.max_daily_loss_pct for r in enabled], default.max_daily_loss_pct),
            strictest([r.max_weekly_loss_pct for r in enabled], default.max_weekly_loss_pct),
        )

    # ------------------------------------------------------------------ public

    def reconcile(self, now_utc: datetime) -> list[dict]:
        """Feed closed-trade P&L into the daily/weekly guards (see fxbot.reconcile)."""
        return reconcile_closed_trades(
            self.client, self.conn, self.daily_guard, self.weekly_guard, now_utc
        )

    def run_all_once(self, now_utc: datetime) -> list[TradeOutcome]:
        # reconcile FIRST so a freshly tripped lock blocks this pass's entries
        self.last_reconciled = []
        self._reconcile_ok = True
        try:
            self.last_reconciled = self.reconcile(now_utc)
        except Exception:  # fail closed for entries: the loss guards may be stale
            log.exception("closed-trade reconciliation failed; blocking new entries this pass")
            self._reconcile_ok = False
        self.stale_unmatched = []
        if self._reconcile_ok:
            try:
                self.stale_unmatched = self._find_stale_unmatched(now_utc)
            except Exception:  # cannot verify the books: fail closed for entries
                log.exception("stale-trade check failed; blocking new entries this pass")
                self._reconcile_ok = False
        for stale in self.stale_unmatched:
            log.error(
                "UNRECONCILED TRADE: %s ticket %s (trade id %s, entered %s) is still open in the DB "
                "but has no closing deal and no open broker position; the daily/weekly loss totals "
                "may be understated - new entries are blocked until it reconciles",
                stale["symbol"], stale["ticket"], stale["trade_id"], stale["entry_time"],
            )
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

        # 1. positions that should already be flat: close them, never open anything new
        stale = [
            p for p in client.get_open_positions(resolved)
            if now_utc >= flat_utc or now_utc < open_utc
            or session_day(self._aware(p.open_time), sym.session.timezone) < today
        ]
        if stale:
            return self._flat_close(sym, stale)
        if now_utc >= flat_utc:
            return TradeOutcome(sym.name, "no_trigger", ["at/after flat-by; no open position"])
        if (resolved, today) in self._attempted:
            return TradeOutcome(
                sym.name, "blocked", [f"an order was already attempted for {resolved} on {today}"]
            )

        # fail closed on the loss books: a failed or incomplete reconciliation may hide losses
        if not self._reconcile_ok:
            return TradeOutcome(
                sym.name, "blocked",
                ["closed-trade reconciliation failed; loss guards may be stale - no new entries"],
            )
        if self.stale_unmatched:
            tickets = ", ".join(str(r["ticket"]) for r in self.stale_unmatched)
            return TradeOutcome(
                sym.name, "blocked",
                [f"unreconciled stale open trade(s) (ticket {tickets}): loss totals may be understated"],
            )

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
                session_bars=known, stop_param=strat.stop_param,
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
            except ValueError as exc:  # fail closed: filter on but cannot evaluate
                return TradeOutcome(
                    sym.name, "filtered", [f"time machine unavailable (insufficient history?): {exc}"]
                )
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
        price = ask if signal.direction == Direction.BUY else bid
        lo, hi = sorted((signal.sl, signal.tp))
        if not (lo < price < hi):
            return TradeOutcome(
                sym.name, "blocked",
                [f"market price {price} outside planned stop/target range ({lo}, {hi})"],
            )

        # 8. size on the LIVE price (the order goes to market, not at signal.entry)
        sl_distance = abs(price - signal.sl)
        live_rr = abs(signal.tp - price) / sl_distance
        if not (live_rr >= sym.risk.min_reward_risk):
            return TradeOutcome(
                sym.name, "blocked",
                [f"live reward/risk too low ({live_rr:.2f} < {sym.risk.min_reward_risk}) at price {price}"],
            )
        balance = client.get_account_balance()
        info = client.get_symbol_info(resolved)
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
        # latch BEFORE the call: if it raises after the broker accepted, we must not retry today
        self._attempted.add((resolved, today))
        order = client.send_order(resolved, signal.direction, lot, signal.sl, signal.tp)
        if not order.success:
            # a clean rejection (e.g. requote) placed nothing: free the symbol to retry next poll
            self._attempted.discard((resolved, today))
            return TradeOutcome(sym.name, "blocked", [f"order rejected: {order.comment}"], order)
        self._record_trade(resolved, now_utc, signal, lot, balance, notes, order.ticket)
        return TradeOutcome(sym.name, "placed", notes, order)

    # ----------------------------------------------------------------- helpers

    def _find_stale_unmatched(self, now_utc: datetime) -> list[dict]:
        """Open `trades` rows (still closed = 0 after reconciliation) that should long be
        over - past flat-by of their entry session day, or older than STALE_HOURS - and
        whose position is not held at the broker. Such a row means a close that was never
        matched (e.g. position id != ticket, or a missed deal)."""
        rows = self.conn.execute("SELECT * FROM trades WHERE closed = 0 ORDER BY id").fetchall()
        if not rows:
            return []
        now_utc = now_utc.astimezone(UTC)
        held_tickets: set[int] = set()
        held_symbols: set[str] = set()
        sym_by_resolved: dict[str, SymbolConfig] = {}
        for sym in self.cfg.symbols:
            if not sym.enabled:
                continue
            try:
                name = self.client.resolve_symbol(sym.name)
            except ValueError:
                continue
            sym_by_resolved[name.upper()] = sym
            for p in self.client.get_open_positions(name):
                held_tickets.add(p.ticket)
                held_symbols.add(p.symbol.upper())

        stale: list[dict] = []
        for row in rows:
            entry = self._aware(datetime.fromisoformat(row["entry_time"])).astimezone(UTC)
            over = now_utc - entry >= timedelta(hours=STALE_HOURS)
            sym = sym_by_resolved.get(row["symbol"].upper())
            if sym is not None:
                _, flat_utc = _session_window_utc(sym, session_day(entry, sym.session.timezone))
                over = over or now_utc >= flat_utc
            if not over:
                continue
            if row["ticket"] is not None:
                held = int(row["ticket"]) in held_tickets
            else:  # no ticket to compare: any position on the symbol might be it
                held = row["symbol"].upper() in held_symbols
            if held:
                continue
            stale.append({
                "trade_id": row["id"], "symbol": row["symbol"], "ticket": row["ticket"],
                "entry_time": row["entry_time"],
            })
        return stale

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

    @staticmethod
    def _aware(t: datetime) -> datetime:
        return t if t.tzinfo is not None and t.utcoffset() is not None else t.replace(tzinfo=UTC)

    def _flat_close(self, sym: SymbolConfig, positions: list[Position]) -> TradeOutcome:
        failed = [p.ticket for p in positions if not self.client.close_position(p.ticket)]
        if failed:
            return TradeOutcome(
                sym.name, "blocked", [f"flat-by close failed for ticket(s) {failed}"]
            )
        return TradeOutcome(
            sym.name, "flat_close", [f"closed {len(positions)} position(s) that should be flat"]
        )

    def _record_trade(
        self, resolved: str, now_utc: datetime, signal: Signal, lot: float,
        balance: float, notes: list[str], ticket: int | None = None,
    ) -> None:
        try:
            self.conn.execute(
                "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv, "
                "entry_balance, ticket) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (resolved, now_utc.isoformat(), signal.direction.value, signal.entry,
                 signal.sl, signal.tp, lot, signal.crv, balance, ticket),
            )
            self.conn.commit()
        except sqlite3.Error as exc:  # the order is already live; surface, don't raise
            log.exception("failed to record trade for %s", resolved)
            notes.append(f"order placed but trade row not recorded: {exc}")
