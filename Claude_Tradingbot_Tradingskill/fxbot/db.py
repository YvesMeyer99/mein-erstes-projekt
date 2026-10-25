import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    direction TEXT NOT NULL CHECK(direction IN ('buy','sell')),
    entry_price REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    lot REAL NOT NULL,
    crv REAL NOT NULL,
    result TEXT,
    pnl REAL,
    pnl_pct REAL,
    entry_balance REAL,
    ticket INTEGER,
    closed INTEGER NOT NULL DEFAULT 0,
    close_price REAL,
    note TEXT,
    UNIQUE(symbol, entry_time)
);

CREATE TABLE IF NOT EXISTS daily_risk (
    date TEXT PRIMARY KEY,
    realized_pnl_pct REAL NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS weekly_risk (
    week_start_date TEXT PRIMARY KEY,
    realized_pnl_pct REAL NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0
);
"""


# Columns added after the first release; init_db adds them to a pre-existing trades table.
# (name, DDL fragment) - ADD COLUMN only accepts constant defaults, which these are.
_TRADES_MIGRATIONS = (
    ("ticket", "INTEGER"),
    ("closed", "INTEGER NOT NULL DEFAULT 0"),
    ("close_price", "REAL"),
    ("note", "TEXT"),          # operator note (fxbot.admin_cli abandon --reason)
)


def _migrate_trades(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
    for name, ddl in _TRADES_MIGRATIONS:
        if name not in existing:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")


def get_connection(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    _migrate_trades(conn)
    conn.commit()
    return conn
