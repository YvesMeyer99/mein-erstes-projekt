import json
from datetime import datetime, timedelta, timezone

import pytest

from fxbot import admin_cli
from fxbot.db import init_db

UTC = timezone.utc
ENTRY = "2026-01-12T08:20:00+00:00"        # Monday
CLOSE = "2026-01-12T10:30:00+00:00"        # Monday
DAY = "2026-01-12"
WEEK = "2026-01-12"
LATER_CLOSE = "2026-01-21T10:30:00+00:00"  # Wednesday of the following week
LATER_WEEK = "2026-01-19"

INSERT = (
    "INSERT INTO trades (symbol, entry_time, direction, entry_price, sl, tp, lot, crv, entry_balance, ticket) "
    "VALUES (?,?,?,?,?,?,?,?,?,?)"
)


@pytest.fixture
def env(tmp_path):
    """A real DB file + config file (daily cap 3%, weekly cap 6%) the CLI can open."""
    db = tmp_path / "bot.db"
    conn = init_db(str(db))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "timeframe": "M5",
        "risk": {"max_daily_loss_pct": 3.0, "max_weekly_loss_pct": 6.0},
        "symbols": [{"name": "EURUSD", "enabled": True}],
    }), encoding="utf-8")
    return conn, str(db), str(cfg)


def _trade(conn, entry=ENTRY, symbol="EURUSD", ticket=101, balance=10_000.0):
    cur = conn.execute(INSERT, (symbol, entry, "buy", 1.1, 1.09, 1.12, 0.5, 2.0, balance, ticket))
    conn.commit()
    return cur.lastrowid


def _run(env, *args):
    _, db, cfg = env
    return admin_cli.main(["--db", db, "--config", cfg, *args])


def _row(conn, tid):
    return conn.execute("SELECT * FROM trades WHERE id = ?", (tid,)).fetchone()


def _daily(conn, date):
    return conn.execute("SELECT * FROM daily_risk WHERE date = ?", (date,)).fetchone()


def _weekly(conn, week):
    return conn.execute("SELECT * FROM weekly_risk WHERE week_start_date = ?", (week,)).fetchone()


def test_close_pnl_pct_feeds_both_guards_and_marks_closed(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-2", "--close-time", CLOSE,
                "--close-price", "1.095") == 0
    row = _row(conn, tid)
    assert row["closed"] == 1
    assert row["pnl_pct"] == pytest.approx(-2.0)
    assert row["pnl"] == pytest.approx(-200.0)         # -2% of entry_balance 10000
    assert row["close_price"] == pytest.approx(1.095)
    assert row["exit_time"] == CLOSE
    assert row["result"] == "loss"
    assert _daily(conn, DAY)["realized_pnl_pct"] == pytest.approx(-2.0)
    assert _weekly(conn, WEEK)["realized_pnl_pct"] == pytest.approx(-2.0)
    out = capsys.readouterr().out
    assert "closed trade" in out and str(tid) in out


def test_close_profit_computes_pnl_pct_from_entry_balance(env):
    conn = env[0]
    tid = _trade(conn, balance=5_000.0)
    assert _run(env, "close", "--id", str(tid), "--profit", "-150", "--close-time", CLOSE) == 0
    row = _row(conn, tid)
    assert row["pnl"] == pytest.approx(-150.0)
    assert row["pnl_pct"] == pytest.approx(-3.0)       # -150 / 5000 * 100
    assert _daily(conn, DAY)["realized_pnl_pct"] == pytest.approx(-3.0)
    assert _daily(conn, DAY)["is_locked"] == 1          # -3% hits the 3% cap


def test_close_profit_without_entry_balance_is_refused(env, capsys):
    conn = env[0]
    tid = _trade(conn, balance=None)
    assert _run(env, "close", "--id", str(tid), "--profit", "-50", "--close-time", CLOSE) == 2
    assert _row(conn, tid)["closed"] == 0
    assert _daily(conn, DAY) is None
    assert "entry_balance" in capsys.readouterr().err


def test_manual_losing_closes_lock_the_day_and_latch(env):
    conn = env[0]
    a = _trade(conn, ticket=1)
    b = _trade(conn, entry="2026-01-12T09:00:00+00:00", ticket=2)
    c = _trade(conn, entry="2026-01-12T09:30:00+00:00", ticket=3)
    assert _run(env, "close", "--id", str(a), "--pnl-pct", "-1.5", "--close-time", CLOSE) == 0
    assert _daily(conn, DAY)["is_locked"] == 0
    assert _run(env, "close", "--id", str(b), "--pnl-pct", "-1.5", "--close-time", CLOSE) == 0
    assert _daily(conn, DAY)["is_locked"] == 1
    # a recovery afterwards must not unlock (latched)
    assert _run(env, "close", "--id", str(c), "--pnl-pct", "2", "--close-time", CLOSE) == 0
    d = _daily(conn, DAY)
    assert d["realized_pnl_pct"] == pytest.approx(-1.0)
    assert d["is_locked"] == 1


def test_close_uses_close_date_and_its_monday_for_the_week(env):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", LATER_CLOSE) == 0
    assert _daily(conn, "2026-01-21")["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _weekly(conn, LATER_WEEK)["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _weekly(conn, WEEK) is None


def test_close_time_default_is_now_utc(env):
    conn = env[0]
    b = _trade(conn, entry="2026-01-12T09:00:00+00:00", ticket=2)
    before = datetime.now(UTC)
    assert _run(env, "close", "--id", str(b), "--pnl-pct", "-1") == 0
    exit_time = datetime.fromisoformat(_row(conn, b)["exit_time"])
    assert before <= exit_time <= datetime.now(UTC)


def test_naive_close_time_requires_the_server_offset(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", "2026-01-12T10:30:00") == 2
    assert "server-utc-offset-hours" in capsys.readouterr().err
    assert _row(conn, tid)["closed"] == 0 and _daily(conn, DAY) is None


def test_naive_close_time_is_converted_from_server_time(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    # server clock (UTC+3) shows Tue 01:30 -> 22:30 UTC on Monday 2026-01-12: Monday bucket, not Tuesday
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", "2026-01-13T01:30:00",
                "--server-utc-offset-hours", "3") == 0
    assert _row(conn, tid)["exit_time"] == "2026-01-12T22:30:00+00:00"
    assert _daily(conn, "2026-01-12")["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _daily(conn, "2026-01-13") is None
    out = capsys.readouterr().out
    assert "2026-01-12T22:30:00+00:00 UTC" in out and "Monday 2026-01-12" in out


def test_server_time_straddling_utc_midnight_into_the_next_week(env):
    conn = env[0]
    tid = _trade(conn, entry="2026-01-18T20:00:00+00:00")     # Sunday
    # server (UTC+2) shows Sun 23:30 = 21:30 UTC Sunday -> still the old week (Monday 2026-01-12)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", "2026-01-18T23:30:00",
                "--server-utc-offset-hours", "2") == 0
    assert _weekly(conn, "2026-01-12")["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _weekly(conn, "2026-01-19") is None


def test_server_offset_can_move_a_close_into_the_next_utc_day(env):
    conn = env[0]
    tid = _trade(conn, entry="2026-01-18T20:00:00+00:00")
    # negative offset (UTC-5): server Sun 20:30 = Mon 01:30 UTC -> new week
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", "2026-01-18T20:30:00",
                "--server-utc-offset-hours", "-5") == 0
    assert _weekly(conn, "2026-01-19")["realized_pnl_pct"] == pytest.approx(-1.0)


def test_explicit_offset_in_close_time_wins_over_server_offset(env):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1",
                "--close-time", "2026-01-12T12:30:00+02:00") == 0
    assert _row(conn, tid)["exit_time"] == CLOSE


@pytest.mark.parametrize("off", ["99", "nan"])
def test_implausible_server_offset_is_refused(env, off):
    tid = _trade(env[0])
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", "2026-01-12T10:30:00",
                "--server-utc-offset-hours", off) == 2
    assert _row(env[0], tid)["closed"] == 0


def test_future_close_time_is_refused(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", future) == 2
    assert "future" in capsys.readouterr().err
    assert _row(conn, tid)["closed"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM daily_risk").fetchone()["c"] == 0


def test_close_time_within_slack_of_now_is_accepted(env):
    tid = _trade(env[0])
    near = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", near) == 0


def test_profit_overflowing_the_percentage_is_refused(env, capsys):
    conn = env[0]
    tid = _trade(conn, balance=1e-320)
    assert _run(env, "close", "--id", str(tid), "--profit", "1e300", "--close-time", CLOSE) == 2
    assert "overflow" in capsys.readouterr().err
    assert _row(conn, tid)["closed"] == 0 and _daily(conn, DAY) is None


def test_pnl_pct_overflowing_the_profit_is_refused(env, capsys):
    conn = env[0]
    tid = _trade(conn, balance=1e308)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "1e308", "--close-time", CLOSE) == 2
    assert "overflow" in capsys.readouterr().err
    assert _row(conn, tid)["closed"] == 0 and _daily(conn, DAY) is None


def test_db_path_from_env_needs_no_mt5_credentials(env, monkeypatch, capsys):
    conn, db, _ = env
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DB_PATH", db)
    _trade(conn, ticket=4242)
    assert admin_cli.main(["list-open"]) == 0
    assert "4242" in capsys.readouterr().out
    assert admin_cli.main(["abandon", "--id", "1", "--reason", "env db"]) == 0
    assert _row(conn, 1)["closed"] == 1


def test_missing_env_db_path_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "absent.db"))
    assert admin_cli.main(["list-open"]) == 2
    assert not (tmp_path / "absent.db").exists()


def test_close_refuses_close_time_before_entry(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1",
                "--close-time", "2026-01-12T07:00:00+00:00") == 2
    assert _row(conn, tid)["closed"] == 0
    assert "before" in capsys.readouterr().err


def test_close_requires_exactly_one_of_pnl_pct_and_profit(env):
    conn = env[0]
    tid = _trade(conn)
    with pytest.raises(SystemExit) as e:
        _run(env, "close", "--id", str(tid))
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--profit", "-100")
    assert e.value.code == 2
    assert _row(conn, tid)["closed"] == 0


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_close_rejects_non_finite_pnl(env, bad):
    conn = env[0]
    tid = _trade(conn)
    # "=" form so argparse does not take "-inf" for an option name
    assert _run(env, "close", "--id", str(tid), f"--pnl-pct={bad}", "--close-time", CLOSE) == 2
    assert _row(conn, tid)["closed"] == 0
    assert _daily(conn, DAY) is None


def test_close_second_time_is_refused_and_does_not_double_count(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", CLOSE) == 0
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", CLOSE) == 2
    assert "already closed" in capsys.readouterr().err
    assert _daily(conn, DAY)["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _weekly(conn, WEEK)["realized_pnl_pct"] == pytest.approx(-1.0)


def test_close_unknown_id_is_refused(env, capsys):
    assert _run(env, "close", "--id", "999", "--pnl-pct", "-1", "--close-time", CLOSE) == 2
    assert "not found" in capsys.readouterr().err
    assert _daily(env[0], DAY) is None


def test_abandon_marks_closed_without_touching_guards(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "abandon", "--id", str(tid), "--reason", "never reached the broker") == 0
    row = _row(conn, tid)
    assert row["closed"] == 1
    assert row["result"] == "abandoned"
    assert row["pnl"] is None and row["pnl_pct"] is None
    assert row["note"] == "never reached the broker"
    assert conn.execute("SELECT COUNT(*) c FROM daily_risk").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM weekly_risk").fetchone()["c"] == 0
    assert "abandoned" in capsys.readouterr().out


def test_abandon_leaves_existing_guard_totals_unchanged(env):
    conn = env[0]
    a = _trade(conn, ticket=1)
    b = _trade(conn, entry="2026-01-12T09:00:00+00:00", ticket=2)
    assert _run(env, "close", "--id", str(a), "--pnl-pct", "-1", "--close-time", CLOSE) == 0
    assert _run(env, "abandon", "--id", str(b), "--reason", "phantom") == 0
    assert _daily(conn, DAY)["realized_pnl_pct"] == pytest.approx(-1.0)
    assert _weekly(conn, WEEK)["realized_pnl_pct"] == pytest.approx(-1.0)


def test_abandon_requires_a_non_blank_reason(env):
    conn = env[0]
    tid = _trade(conn)
    with pytest.raises(SystemExit) as e:
        _run(env, "abandon", "--id", str(tid))
    assert e.value.code == 2
    assert _run(env, "abandon", "--id", str(tid), "--reason", "   ") == 2
    assert _row(conn, tid)["closed"] == 0


def test_abandon_refuses_unknown_and_already_closed(env, capsys):
    conn = env[0]
    tid = _trade(conn)
    assert _run(env, "abandon", "--id", "999", "--reason", "x") == 2
    assert "not found" in capsys.readouterr().err
    assert _run(env, "abandon", "--id", str(tid), "--reason", "x") == 0
    assert _run(env, "abandon", "--id", str(tid), "--reason", "again") == 2
    assert "already closed" in capsys.readouterr().err
    assert _row(conn, tid)["note"] == "x"
    # an abandoned row cannot be closed afterwards either
    assert _run(env, "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", CLOSE) == 2
    assert _daily(conn, DAY) is None


def test_list_open_shows_only_open_rows(env, capsys):
    conn = env[0]
    open_id = _trade(conn, ticket=777)
    done = _trade(conn, entry="2026-01-12T09:00:00+00:00", symbol="GBPUSD", ticket=888)
    assert _run(env, "abandon", "--id", str(done), "--reason", "x") == 0
    capsys.readouterr()
    assert _run(env, "list-open") == 0
    out = capsys.readouterr().out
    assert "EURUSD" in out and "777" in out and ENTRY in out and "10000" in out
    assert "GBPUSD" not in out and "888" not in out
    assert str(open_id) in out


def test_list_open_with_nothing_open(env, capsys):
    assert _run(env, "list-open") == 0
    assert "no open trades" in capsys.readouterr().out.lower()


def test_list_open_does_not_need_a_config_file(tmp_path):
    db = tmp_path / "x.db"
    conn = init_db(str(db))
    _trade(conn)
    assert admin_cli.main(["--db", str(db), "--config", str(tmp_path / "missing.json"), "list-open"]) == 0


def test_close_needs_a_readable_config_because_the_latch_depends_on_the_caps(env, tmp_path, capsys):
    conn, db, _ = env
    tid = _trade(conn)
    assert admin_cli.main(["--db", db, "--config", str(tmp_path / "missing.json"),
                           "close", "--id", str(tid), "--pnl-pct", "-1", "--close-time", CLOSE]) == 2
    assert _row(conn, tid)["closed"] == 0
    assert "config" in capsys.readouterr().err.lower()


def test_close_uses_the_engines_strictest_caps(tmp_path):
    db = tmp_path / "bot.db"
    conn = init_db(str(db))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "timeframe": "M5",
        "risk": {"risk_per_trade_pct": 0.4, "max_daily_loss_pct": 5.0, "max_weekly_loss_pct": 10.0},
        "symbols": [{"name": "EURUSD", "enabled": True},
                    {"name": "GBPUSD", "enabled": True, "overrides": {"max_daily_loss_pct": 1.0}}],
    }), encoding="utf-8")
    tid = _trade(conn)
    assert admin_cli.main(["--db", str(db), "--config", str(cfg), "close", "--id", str(tid),
                           "--pnl-pct", "-1.2", "--close-time", CLOSE]) == 0
    assert _daily(conn, DAY)["is_locked"] == 1      # strictest daily cap (1.0) applies


def test_missing_db_file_is_an_error_not_a_fresh_database(tmp_path, capsys):
    path = tmp_path / "nope" / "bot.db"
    assert admin_cli.main(["--db", str(path), "list-open"]) == 2
    assert not path.exists()
    assert "not found" in capsys.readouterr().err.lower()


def test_old_database_without_note_column_is_migrated(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    raw = sqlite3.connect(str(db))
    raw.executescript(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, "
        "entry_time TEXT NOT NULL, exit_time TEXT, direction TEXT NOT NULL, entry_price REAL NOT NULL, "
        "sl REAL NOT NULL, tp REAL NOT NULL, lot REAL NOT NULL, crv REAL NOT NULL, result TEXT, pnl REAL, "
        "pnl_pct REAL, entry_balance REAL, ticket INTEGER, closed INTEGER NOT NULL DEFAULT 0, "
        "close_price REAL, UNIQUE(symbol, entry_time));"
    )
    raw.execute(INSERT, ("EURUSD", ENTRY, "buy", 1.1, 1.09, 1.12, 0.5, 2.0, 10_000.0, 1))
    raw.commit()
    raw.close()
    assert admin_cli.main(["--db", str(db), "abandon", "--id", "1", "--reason", "old db"]) == 0
    conn = init_db(str(db))
    assert _row(conn, 1)["note"] == "old db"


def test_guard_keys_match_reconcile_convention():
    from fxbot.reconcile import guard_keys
    assert guard_keys(datetime(2026, 1, 18, 23, 59, tzinfo=UTC)) == ("2026-01-18", "2026-01-12")  # Sunday
    assert guard_keys(datetime(2026, 1, 19, 0, 0, tzinfo=UTC)) == ("2026-01-19", "2026-01-19")    # Monday
