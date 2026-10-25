import sqlite3

import pytest

from fxbot.db import init_db

INSERT_TRADE = (
    "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv) "
    "VALUES (?,?,?,?,?,?,?,?)"
)
ROW = ("EURUSD", "2026-01-05T08:15:00", "buy", 1.1, 1.09, 1.12, 0.1, 2.0)


def test_init_db_creates_tables():
    conn = init_db(":memory:")
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"daily_risk", "weekly_risk", "trades"} <= names
    assert conn.row_factory is sqlite3.Row


def test_trades_has_symbol_and_entry_time_columns():
    conn = init_db(":memory:")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    assert {"symbol", "entry_time", "pnl_pct"} <= cols


def test_trades_unique_per_symbol_and_entry_time():
    conn = init_db(":memory:")
    conn.execute(INSERT_TRADE, ROW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(INSERT_TRADE, ROW)
    # same time, different symbol is fine
    conn.execute(INSERT_TRADE, ("XAUUSD",) + ROW[1:])
