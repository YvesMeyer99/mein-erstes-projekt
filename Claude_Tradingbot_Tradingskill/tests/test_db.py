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


def test_trades_has_reconciliation_columns_with_defaults():
    conn = init_db(":memory:")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    assert {"closed", "close_price", "pnl", "pnl_pct", "ticket"} <= cols
    conn.execute(INSERT_TRADE, ROW)  # the legacy insert still works
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["closed"] == 0 and row["close_price"] is None and row["ticket"] is None


def test_init_db_migrates_an_old_trades_table_in_place(tmp_path):
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, entry_time TEXT NOT NULL,
            exit_time TEXT, direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),
            entry_price REAL NOT NULL, sl REAL NOT NULL, tp REAL NOT NULL, lot REAL NOT NULL,
            crv REAL NOT NULL, result TEXT, pnl REAL, pnl_pct REAL, entry_balance REAL,
            UNIQUE(symbol, entry_time)
        );
        """
    )
    old.execute(INSERT_TRADE, ROW)
    old.commit()
    old.close()

    conn = init_db(path)
    init_db(path)  # a second init (restart) must be a no-op
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    assert {"closed", "close_price", "ticket"} <= cols
    row = conn.execute("SELECT * FROM trades").fetchone()
    assert row["closed"] == 0 and row["symbol"] == "EURUSD"
