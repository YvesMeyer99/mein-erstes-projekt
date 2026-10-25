from datetime import datetime, timedelta, timezone

import pytest

import fxbot.backtest_cli as backtest_cli
import fxbot.main as main_mod
from fxbot.config import Settings, load_config
import logging

from fxbot.engine import LiveEngine, TradeOutcome

UTC = timezone.utc
CONFIG_EXAMPLE = "config.example.json"


class StubClient:
    """Stands in for LiveMT5Client: no terminal needed."""

    instances: list = []
    connect_ok = True

    def __init__(self, login, password, server, path=None):
        self.args = (login, password, server)
        self.path = path
        self.connected = False
        StubClient.instances.append(self)

    def connect(self) -> bool:
        self.connected = StubClient.connect_ok
        return self.connected


@pytest.fixture(autouse=True)
def _reset_stub():
    StubClient.instances = []
    StubClient.connect_ok = True


def _settings(tmp_path) -> Settings:
    return Settings(
        mt5_login=123, mt5_password="pw", mt5_server="Demo-Server",
        db_path=str(tmp_path / "sub" / "fxbot.db"),
        mt5_path=r"C:\MT5\terminal64.exe",
    )


# ------------------------------------------------------------------ build_engine

def test_build_engine_wires_db_and_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "LiveMT5Client", StubClient)
    cfg = load_config(CONFIG_EXAMPLE)

    engine = main_mod.build_engine(_settings(tmp_path), cfg)

    assert isinstance(engine, LiveEngine)
    assert engine.cfg is cfg
    client = engine.client
    assert isinstance(client, StubClient)
    assert client.args == (123, "pw", "Demo-Server")
    assert client.path == r"C:\MT5\terminal64.exe"
    assert client.connected is True
    tables = {r[0] for r in engine.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "trades" in tables
    assert (tmp_path / "sub" / "fxbot.db").exists()


def test_build_engine_raises_when_connect_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(main_mod, "LiveMT5Client", StubClient)
    StubClient.connect_ok = False
    with pytest.raises(RuntimeError, match="connect"):
        main_mod.build_engine(_settings(tmp_path), load_config(CONFIG_EXAMPLE))


# ---------------------------------------------------------------------- run_loop

class FakeEngine:
    def __init__(self):
        self.calls: list[datetime] = []

    def run_all_once(self, now_utc):
        self.calls.append(now_utc)
        return []


def test_run_loop_runs_once_then_stops_on_flag():
    now = datetime(2026, 1, 12, 8, 20, 30, tzinfo=UTC)
    stop_flag = {"v": False}

    def stop():
        return stop_flag["v"]

    class Eng(FakeEngine):
        def run_all_once(self, now_utc):
            stop_flag["v"] = True  # stop after the first pass
            return super().run_all_once(now_utc)

    engine = Eng()
    main_mod.run_loop(engine, 1, clock=lambda: now, stop=stop, sleep=lambda s: None, settle_seconds=0)
    assert len(engine.calls) == 1
    assert engine.calls[0] == now


def test_run_loop_runs_once_per_closed_bar():
    engine = FakeEngine()
    times = [
        datetime(2026, 1, 12, 8, 20, 1, tzinfo=UTC),
        datetime(2026, 1, 12, 8, 21, 0, tzinfo=UTC),   # same M5 bar -> no new run
        datetime(2026, 1, 12, 8, 24, 59, tzinfo=UTC),  # same bar
        datetime(2026, 1, 12, 8, 25, 2, tzinfo=UTC),   # next bar -> run
    ]
    it = iter(times)
    state = {"used": 0}

    def clock():
        state["used"] += 1
        return next(it)

    def stop():
        return state["used"] >= len(times)

    main_mod.run_loop(engine, 1, clock=clock, stop=stop, sleep=lambda s: None, settle_seconds=0)
    assert engine.calls == [times[0], times[3]]


def test_run_loop_survives_engine_exception():
    class Boom:
        def __init__(self):
            self.n = 0

        def run_all_once(self, now_utc):
            self.n += 1
            raise RuntimeError("terminal hiccup")

    engine = Boom()
    times = iter([datetime(2026, 1, 12, 8, 20, 1, tzinfo=UTC), datetime(2026, 1, 12, 8, 25, 2, tzinfo=UTC)])
    used = {"n": 0}

    def clock():
        used["n"] += 1
        return next(times)

    def stop():
        return used["n"] >= 2

    main_mod.run_loop(engine, 1, clock=clock, stop=stop, sleep=lambda s: None, settle_seconds=0)
    assert engine.n == 2


def _run_one_pass(engine):
    now = datetime(2026, 1, 12, 8, 20, 1, tzinfo=UTC)
    used = {"n": 0}

    def clock():
        used["n"] += 1
        return now

    main_mod.run_loop(engine, 1, clock=clock, stop=lambda: used["n"] >= 1,
                      sleep=lambda s: None, settle_seconds=0)


def test_run_loop_logs_outcomes(caplog):
    class Eng:
        def run_all_once(self, now_utc):
            return [TradeOutcome("EURUSD", "placed", ["note a", "note b"])]

    with caplog.at_level(logging.INFO, logger="fxbot.main"):
        _run_one_pass(Eng())
    assert any("EURUSD: placed note a; note b" in r.getMessage() for r in caplog.records)
    assert not any("run_all_once failed" in r.getMessage() for r in caplog.records)


def test_run_loop_logging_error_not_misattributed_to_engine(caplog):
    class Bad:  # an outcome whose attributes break the logging, after the pass succeeded
        symbol = "EURUSD"
        action = "placed"
        reasons = None  # "; ".join(None) raises TypeError

    class Eng:
        def run_all_once(self, now_utc):
            return [Bad()]

    with caplog.at_level(logging.INFO, logger="fxbot.main"):
        _run_one_pass(Eng())
    messages = [r.getMessage() for r in caplog.records]
    assert not any("run_all_once failed" in m for m in messages)
    assert any("could not log" in m for m in messages)


def test_run_loop_does_not_run_if_stopped_initially():
    engine = FakeEngine()
    main_mod.run_loop(
        engine, 1, clock=lambda: datetime(2026, 1, 12, 8, 20, tzinfo=UTC),
        stop=lambda: True, sleep=lambda s: None, settle_seconds=0,
    )
    assert engine.calls == []


# ------------------------------------------------------------------ backtest CLI

def _write_csv(path):
    start = datetime(2026, 1, 12, 8, 0, tzinfo=UTC)
    lines = ["time,open,high,low,close,volume"]
    for i in range(6):
        t = start + timedelta(minutes=5 * i)
        lines.append(f"{t.isoformat()},1.1000,1.1005,1.0995,1.1000,10")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_backtest_cli_csv_prints_result(tmp_path, capsys):
    csv_path = tmp_path / "eurusd.csv"
    _write_csv(csv_path)
    rc = backtest_cli.main(
        ["--symbol", "eurusd", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "EURUSD" in out
    assert "n_trades" in out and "win_rate" in out and "max_drawdown" in out
    assert "profit_factor" in out


def test_backtest_cli_unknown_symbol_errors(tmp_path, capsys):
    csv_path = tmp_path / "x.csv"
    _write_csv(csv_path)
    rc = backtest_cli.main(
        ["--symbol", "NOPE", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE]
    )
    assert rc != 0
    assert "NOPE" in capsys.readouterr().err


def test_backtest_cli_csv_requires_file(capsys):
    rc = backtest_cli.main(["--symbol", "EURUSD", "--source", "csv", "--config", CONFIG_EXAMPLE])
    assert rc != 0
    assert "--file" in capsys.readouterr().err


def test_backtest_cli_mt5_requires_dates(capsys):
    rc = backtest_cli.main(["--symbol", "EURUSD", "--source", "mt5", "--config", CONFIG_EXAMPLE])
    assert rc != 0
    assert "--from" in capsys.readouterr().err


def test_backtest_cli_mt5_source_uses_client(monkeypatch, capsys):
    calls = {}

    def fake_bars_from_mt5(client, symbol, timeframe, start, end):
        calls["args"] = (symbol, timeframe, start, end)
        return []

    monkeypatch.setattr(backtest_cli, "LiveMT5Client", StubClient)
    monkeypatch.setattr(backtest_cli, "bars_from_mt5", fake_bars_from_mt5)
    monkeypatch.setattr(
        backtest_cli, "load_settings",
        lambda: Settings(mt5_login=1, mt5_password="pw", mt5_server="s", db_path="x"),
    )
    rc = backtest_cli.main(
        ["--symbol", "EURUSD", "--source", "mt5", "--from", "2026-07-01", "--to", "2026-10-01",
         "--config", CONFIG_EXAMPLE]
    )
    assert rc == 0
    assert calls["args"] == (
        "EURUSD", "M5", datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
    )
    assert "pw" not in capsys.readouterr().out


def _capture_contract_size(monkeypatch):
    seen = {}
    real = backtest_cli.run_backtest

    def spy(bars, sym, starting_balance=10_000.0, contract_size=100_000.0, apply_risk_gates=True):
        seen["contract_size"] = contract_size
        seen["apply_risk_gates"] = apply_risk_gates
        return real(
            bars, sym, starting_balance=starting_balance, contract_size=contract_size,
            apply_risk_gates=apply_risk_gates,
        )

    monkeypatch.setattr(backtest_cli, "run_backtest", spy)
    return seen


def test_backtest_cli_uses_symbol_contract_size_from_config(tmp_path, monkeypatch):
    csv_path = tmp_path / "xau.csv"
    _write_csv(csv_path)
    seen = _capture_contract_size(monkeypatch)
    rc = backtest_cli.main(
        ["--symbol", "XAUUSD", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE]
    )
    assert rc == 0 and seen["contract_size"] == 100.0  # metals contract size from config.example.json


def test_backtest_cli_fx_symbol_defaults_to_standard_lot(tmp_path, monkeypatch):
    csv_path = tmp_path / "eur.csv"
    _write_csv(csv_path)
    seen = _capture_contract_size(monkeypatch)
    backtest_cli.main(
        ["--symbol", "EURUSD", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE]
    )
    assert seen["contract_size"] == 100_000.0


def test_backtest_cli_contract_size_flag_overrides_config(tmp_path, monkeypatch):
    csv_path = tmp_path / "xau.csv"
    _write_csv(csv_path)
    seen = _capture_contract_size(monkeypatch)
    backtest_cli.main(
        ["--symbol", "XAUUSD", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE,
         "--contract-size", "50"]
    )
    assert seen["contract_size"] == 50.0


def test_format_result_handles_undefined_profit_factor():
    from fxbot.backtester import BacktestResult
    r = BacktestResult(
        equity_curve=[10_000.0, 10_100.0], win_rate=1.0, avg_crv=2.0, max_drawdown=0.0,
        expectancy=100.0, n_trades=1, profit_factor=None, tp_hits=1, sl_hits=0, flat_hits=0,
    )
    text = backtest_cli.format_result("EURUSD", 10, r)
    assert "profit_factor: n/a" in text and "inf" not in text


def test_backtest_cli_risk_gates_on_by_default(tmp_path, monkeypatch, capsys):
    csv_path = tmp_path / "eur.csv"
    _write_csv(csv_path)
    seen = _capture_contract_size(monkeypatch)
    rc = backtest_cli.main(
        ["--symbol", "EURUSD", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE]
    )
    assert rc == 0 and seen["apply_risk_gates"] is True
    assert "skipped_by_risk" in capsys.readouterr().out


def test_backtest_cli_no_risk_gates_flag_disables_gates(tmp_path, monkeypatch):
    csv_path = tmp_path / "eur.csv"
    _write_csv(csv_path)
    seen = _capture_contract_size(monkeypatch)
    rc = backtest_cli.main(
        ["--symbol", "EURUSD", "--source", "csv", "--file", str(csv_path), "--config", CONFIG_EXAMPLE,
         "--no-risk-gates"]
    )
    assert rc == 0 and seen["apply_risk_gates"] is False
