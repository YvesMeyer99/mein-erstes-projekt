"""Closed-trade reconciliation: feed realized P&L back into the daily/weekly guards.

`LiveEngine` records a `trades` row (closed = 0) when it places an order. The broker
closes the position later (stop, target or the engine's flat-by close). This module
finds the broker's closing deal for every still-open row, stores the result on the row
and calls `record_pnl` on the guards, so the %-loss limits can actually lock trading.

Design notes / decisions:
  * Matching is by broker position id (== the order ticket stored in `trades.ticket`)
    plus symbol. Rows without a ticket (legacy / ticket not captured) fall back to
    symbol + "closed after the entry" + same lot, and the fallback never takes a deal
    whose position id already belongs to another trades row, so one close can never
    be counted twice.
  * Idempotent: only `closed = 0` rows are considered and the row is marked closed in
    the same transaction that records the guard P&L (`record_pnl` commits, which also
    commits the pending UPDATE). A second run therefore finds nothing to do.
  * The guard date is the UTC date of the CLOSE time and the week start is that
    date's Monday - the same convention `LiveEngine` uses for `server_date` /
    `week_start` when it asks the risk gate.
  * The guards stay latched (see `risk.py`): a recovery after a lock never unlocks.
  * The deal window always reaches back to the oldest still-open row (clamped to
    MAX_WINDOW), so a bot that was down for a while still finds old closes.
"""
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from fxbot.mt5_types import ClosedDeal, MT5Client
from fxbot.risk import DailyRiskGuard, WeeklyRiskGuard

log = logging.getLogger(__name__)

UTC = timezone.utc
DEFAULT_LOOKBACK = timedelta(days=5)
MAX_WINDOW = timedelta(days=30)        # never ask the broker for more history than this
WINDOW_PAD = timedelta(minutes=5)      # entry rows are stamped at poll time, a hair after the fill
END_SLACK = timedelta(minutes=5)       # tolerate small clock skew on the broker's close time
LOT_ABS_TOL = 1e-6


def _parse_utc(text: str) -> datetime:
    t = datetime.fromisoformat(text)
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def guard_keys(close_utc: datetime) -> tuple[str, str]:
    """(daily key, weekly key) a close at `close_utc` is booked under: the UTC date of the
    close and that date's Monday. Shared with the operator CLI so both always agree."""
    close_date = close_utc.astimezone(UTC).date()
    return close_date.isoformat(), (close_date - timedelta(days=close_date.weekday())).isoformat()


def _match(row: sqlite3.Row, by_position: dict[int, ClosedDeal], pool: list[ClosedDeal],
           taken: set[int], known_tickets: set[int]) -> ClosedDeal | None:
    symbol = row["symbol"].upper()
    if row["ticket"] is not None:
        deal = by_position.get(int(row["ticket"]))
        if deal is not None and deal.symbol.upper() == symbol and deal.position_id not in taken:
            return deal
        return None
    entry = _parse_utc(row["entry_time"])
    candidates = [
        d for d in pool
        if d.symbol.upper() == symbol
        and d.position_id not in taken
        and d.position_id not in known_tickets
        and d.close_time >= entry
        and math.isclose(d.volume, row["lot"], rel_tol=0.0, abs_tol=LOT_ABS_TOL)
    ]
    return min(candidates, key=lambda d: d.close_time) if candidates else None


def reconcile_closed_trades(
    client: MT5Client,
    conn: sqlite3.Connection,
    daily_guard: DailyRiskGuard,
    weekly_guard: WeeklyRiskGuard,
    now_utc: datetime,
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> list[dict]:
    """Reconcile every open `trades` row that the broker has since closed.

    Returns one summary dict per row reconciled in this call (empty when nothing
    closed). Rows without a closing deal stay open for a later call. Exceptions from
    the client propagate (the caller decides how to fail).
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError(f"now_utc must be timezone-aware, got naive {now_utc!r}")
    now_utc = now_utc.astimezone(UTC)

    open_rows = conn.execute("SELECT * FROM trades WHERE closed = 0 ORDER BY id").fetchall()
    if not open_rows:
        return []

    oldest_entry = min(_parse_utc(r["entry_time"]) for r in open_rows)
    start = min(now_utc - lookback, oldest_entry - WINDOW_PAD)
    start = max(start, now_utc - MAX_WINDOW)
    deals = client.get_closed_deals(start, now_utc + END_SLACK)
    if not deals:
        return []

    by_position = {d.position_id: d for d in deals}
    known_tickets = {
        int(r["ticket"]) for r in conn.execute("SELECT ticket FROM trades WHERE ticket IS NOT NULL")
    }
    taken: set[int] = set()
    reconciled: list[dict] = []

    for row in open_rows:
        deal = _match(row, by_position, deals, taken, known_tickets)
        if deal is None:
            continue

        balance = row["entry_balance"]
        if balance is None or not balance > 0:
            balance = client.get_account_balance()
            log.warning("trade %s has no entry_balance; using the current balance %s", row["id"], balance)
        if not balance > 0:
            log.error("cannot size P&L of trade %s: no positive balance; leaving it open", row["id"])
            continue
        taken.add(deal.position_id)

        pnl_pct = deal.profit / balance * 100.0
        close_utc = deal.close_time.astimezone(UTC)
        date_key, week_key = guard_keys(close_utc)
        result = "win" if deal.profit > 0 else "loss" if deal.profit < 0 else "breakeven"

        try:
            cur = conn.execute(
                "UPDATE trades SET closed = 1, exit_time = ?, close_price = ?, pnl = ?, pnl_pct = ?, "
                "result = ?, ticket = COALESCE(ticket, ?) WHERE id = ? AND closed = 0",
                (close_utc.isoformat(), deal.close_price, deal.profit, pnl_pct, result,
                 deal.position_id, row["id"]),
            )
            if cur.rowcount != 1:  # someone else closed it in the meantime: do not double count
                conn.rollback()
                continue
            # record_pnl commits, which also commits the UPDATE above (one unit of work)
            was_locked = daily_guard.is_locked(date_key)
            daily_guard.record_pnl(date_key, pnl_pct)
            weekly_guard.record_pnl(week_key, pnl_pct)
        except Exception:
            conn.rollback()
            raise

        if daily_guard.is_locked(date_key) and not was_locked:
            log.warning("daily loss/win limit reached for %s (realized %.2f%%): trading locked",
                        date_key, daily_guard.realized_pnl_pct(date_key))
        log.info("reconciled %s ticket %s: %s %.2f (%.2f%%)",
                 row["symbol"], deal.position_id, result, deal.profit, pnl_pct)
        reconciled.append({
            "trade_id": row["id"],
            "symbol": row["symbol"],
            "ticket": deal.position_id,
            "profit": deal.profit,
            "pnl_pct": pnl_pct,
            "close_price": deal.close_price,
            "close_time": close_utc,
            "date": date_key,
            "week_start": week_key,
            "daily_locked": daily_guard.is_locked(date_key),
            "weekly_locked": weekly_guard.is_locked(week_key),
        })

    return reconciled
