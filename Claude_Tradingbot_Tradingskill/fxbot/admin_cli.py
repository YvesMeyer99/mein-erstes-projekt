"""Operator CLI for the bot's SQLite DB: clear a trade row that can never auto-reconcile.

    python -m fxbot.admin_cli list-open
    python -m fxbot.admin_cli close --id 7 --profit -52.30 [--close-time ISO] [--close-price P]
    python -m fxbot.admin_cli close --id 7 --pnl-pct -0.52
    python -m fxbot.admin_cli abandon --id 7 --reason "order never reached the broker"

A `trades` row that stays open with no closing deal and no broker position fail-closes ALL new
entries (see `LiveEngine._find_stale_unmatched`). These commands let a human settle ONE row:

  * `close`   - the trade really closed at the broker: book its real P&L into the daily/weekly
                guards (same date / Monday-week keys and the same strictest caps as the live
                engine, so totals and the lock latch stay correct) and mark the row closed.
  * `abandon` - the row is a phantom (never reached the broker): mark it closed WITHOUT feeding
                the guards.

Single row, explicit, idempotent (a closed or unknown id is refused, exit code 2). This writes to
the live DB - run it while the bot is stopped.
"""
import argparse
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from fxbot.config import load_config, load_settings
from fxbot.db import init_db
from fxbot.engine import LiveEngine
from fxbot.reconcile import _parse_utc, guard_keys
from fxbot.risk import DailyRiskGuard, WeeklyRiskGuard

UTC = timezone.utc


class AdminError(Exception):
    """A refused operation; the message is shown to the operator (exit code 2)."""


# --------------------------------------------------------------------------- core operations


def _get_open_row(conn: sqlite3.Connection, trade_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if row is None:
        raise AdminError(f"trade id {trade_id} not found")
    if row["closed"]:
        raise AdminError(f"trade id {trade_id} is already closed (result: {row['result'] or 'n/a'}); nothing changed")
    return row


def list_open(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM trades WHERE closed = 0 ORDER BY id").fetchall()


def close_trade(
    conn: sqlite3.Connection,
    daily_guard: DailyRiskGuard,
    weekly_guard: WeeklyRiskGuard,
    trade_id: int,
    *,
    pnl_pct: float | None = None,
    profit: float | None = None,
    close_time: datetime | None = None,
    close_price: float | None = None,
) -> dict:
    """Manually reconcile ONE open row; mirrors `reconcile_closed_trades` for a single row."""
    if (pnl_pct is None) == (profit is None):
        raise AdminError("give exactly one of --pnl-pct or --profit")
    row = _get_open_row(conn, trade_id)

    balance = row["entry_balance"]
    if profit is not None:
        if not math.isfinite(profit):
            raise AdminError(f"--profit must be a finite number, got {profit}")
        if balance is None or not balance > 0:
            raise AdminError(
                f"trade id {trade_id} has no positive entry_balance, cannot derive a percentage "
                "from --profit; pass --pnl-pct instead"
            )
        pnl_pct = profit / balance * 100.0
    else:
        if not math.isfinite(pnl_pct):
            raise AdminError(f"--pnl-pct must be a finite number, got {pnl_pct}")
        if balance is not None and balance > 0:
            profit = pnl_pct / 100.0 * balance
    if close_price is not None and not math.isfinite(close_price):
        raise AdminError(f"--close-price must be a finite number, got {close_price}")

    close_utc = (datetime.now(UTC) if close_time is None else _as_utc(close_time))
    if close_utc < _parse_utc(row["entry_time"]):
        raise AdminError(
            f"close time {close_utc.isoformat()} is before the trade's entry {row['entry_time']}"
        )
    date_key, week_key = guard_keys(close_utc)
    result = "win" if pnl_pct > 0 else "loss" if pnl_pct < 0 else "breakeven"

    try:
        cur = conn.execute(
            "UPDATE trades SET closed = 1, exit_time = ?, close_price = ?, pnl = ?, pnl_pct = ?, "
            "result = ? WHERE id = ? AND closed = 0",
            (close_utc.isoformat(), close_price, profit, pnl_pct, result, trade_id),
        )
        if cur.rowcount != 1:  # closed by someone else in the meantime: do not double count
            conn.rollback()
            raise AdminError(f"trade id {trade_id} is already closed; nothing changed")
        # record_pnl commits, which also commits the UPDATE above (one unit of work)
        daily_guard.record_pnl(date_key, pnl_pct)
        weekly_guard.record_pnl(week_key, pnl_pct)
    except Exception:
        conn.rollback()
        raise

    return {
        "trade_id": trade_id, "symbol": row["symbol"], "pnl_pct": pnl_pct, "profit": profit,
        "close_time": close_utc, "date": date_key, "week_start": week_key, "result": result,
        "daily_realized_pct": daily_guard.realized_pnl_pct(date_key),
        "weekly_realized_pct": weekly_guard.realized_pnl_pct(week_key),
        "daily_locked": daily_guard.is_locked(date_key),
        "weekly_locked": weekly_guard.is_locked(week_key),
    }


def abandon_trade(conn: sqlite3.Connection, trade_id: int, reason: str) -> dict:
    """Mark ONE open row closed WITHOUT touching the daily/weekly guards."""
    reason = (reason or "").strip()
    if not reason:
        raise AdminError("--reason must not be empty")
    row = _get_open_row(conn, trade_id)
    cur = conn.execute(
        "UPDATE trades SET closed = 1, result = 'abandoned', note = ? WHERE id = ? AND closed = 0",
        (reason, trade_id),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise AdminError(f"trade id {trade_id} is already closed; nothing changed")
    conn.commit()
    return {"trade_id": trade_id, "symbol": row["symbol"], "reason": reason}


def _as_utc(t: datetime) -> datetime:
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


# --------------------------------------------------------------------------- CLI


def _parse_time(text: str) -> datetime:
    try:
        return _parse_utc(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 timestamp: {text!r}") from None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Operator tool: clear an unreconciled trade row (writes to the live DB; stop the bot first).")
    p.add_argument("--db", help="SQLite file (default: DB_PATH from the environment / .env, data/fxbot.db)")
    p.add_argument("--config", default="config.json",
                   help="config.json; `close` reads the loss caps from it (default: config.json)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list-open", help="list all open (closed=0) trade rows")

    c = sub.add_parser("close", help="book the real P&L of ONE open row and mark it closed")
    c.add_argument("--id", type=int, required=True, help="trades.id (see list-open)")
    grp = c.add_mutually_exclusive_group(required=True)
    grp.add_argument("--pnl-pct", type=float, help="realized P&L as %% of the account balance (negative = loss)")
    grp.add_argument("--profit", type=float,
                     help="realized net profit in account currency; pnl_pct = profit / entry_balance * 100")
    c.add_argument("--close-time", type=_parse_time,
                   help="ISO-8601 close time (naive = UTC); decides the guard day/week. Default: now (UTC)")
    c.add_argument("--close-price", type=float, help="optional close price to store on the row")

    a = sub.add_parser("abandon", help="mark ONE open row closed WITHOUT booking any P&L (phantom row)")
    a.add_argument("--id", type=int, required=True, help="trades.id (see list-open)")
    a.add_argument("--reason", required=True, help="why this row is being abandoned (stored on the row)")
    return p


def _resolve_db_path(arg: str | None) -> str:
    path = arg
    if path is None:
        try:
            path = load_settings().db_path
        except ValueError as exc:
            raise AdminError(f"{exc} (or pass --db PATH)") from None
    if path != ":memory:" and not Path(path).is_file():
        raise AdminError(f"database file not found: {path} (refusing to create a new one)")
    return path


def _fmt(value) -> str:
    return "-" if value is None else f"{value:g}" if isinstance(value, float) else str(value)


def _print_open(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("no open trades")
        return
    cols = ("id", "symbol", "ticket", "entry_time", "direction", "lot", "entry_balance")
    table = [cols] + [tuple(_fmt(r[c]) for c in cols) for r in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(cols))]
    for line in table:
        print("  ".join(cell.ljust(w) for cell, w in zip(line, widths)).rstrip())
    print(f"{len(rows)} open trade(s)")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        conn = init_db(_resolve_db_path(args.db))
        if args.command == "list-open":
            _print_open(list_open(conn))
        elif args.command == "close":
            try:
                daily_cap, weekly_cap = LiveEngine._strictest_loss_caps(load_config(args.config))
            except (OSError, ValueError) as exc:
                raise AdminError(
                    f"cannot read config {args.config!r} ({exc}); `close` needs it for the loss caps "
                    "that decide the lock (pass --config PATH)"
                ) from None
            r = close_trade(
                conn, DailyRiskGuard(conn, daily_cap), WeeklyRiskGuard(conn, weekly_cap), args.id,
                pnl_pct=args.pnl_pct, profit=args.profit,
                close_time=args.close_time, close_price=args.close_price,
            )
            print(
                f"closed trade {r['trade_id']} ({r['symbol']}): {r['result']} {r['pnl_pct']:+.2f}% booked on "
                f"{r['date']} (day total {r['daily_realized_pct']:+.2f}%, "
                f"{'LOCKED' if r['daily_locked'] else 'open'}) and week of {r['week_start']} "
                f"(week total {r['weekly_realized_pct']:+.2f}%, "
                f"{'LOCKED' if r['weekly_locked'] else 'open'})"
            )
        else:
            r = abandon_trade(conn, args.id, args.reason)
            print(f"abandoned trade {r['trade_id']} ({r['symbol']}): marked closed, "
                  f"no P&L booked (reason: {r['reason']})")
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"error: database problem: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
