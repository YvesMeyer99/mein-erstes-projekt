import json

import pytest

from fxbot.config import load_config, load_settings

EXAMPLE_JSON = """
{
  "timeframe": "M5",
  "risk": {
    "risk_per_trade_pct": 1.0,
    "max_daily_loss_pct": 3.0,
    "max_weekly_loss_pct": 6.0,
    "max_trades_per_day": 3,
    "min_reward_risk": 1.5,
    "max_open_positions": 3
  },
  "session": { "timezone": "Europe/London", "open": "08:00", "flat_by": "20:00" },
  "strategy": {
    "or_minutes": 15,
    "stop_rule": "or_mid",
    "target_r": 2.0,
    "allow_short": true,
    "max_spread_points": 30
  },
  "timemachine_filter": { "enabled": false, "min_p_green": 0.5, "replays": 10000, "seed": 19 },
  "symbols": [
    { "name": "EURUSD", "enabled": true },
    { "name": "GBPUSD", "enabled": true },
    { "name": "XAUUSD", "enabled": true, "overrides": { "or_minutes": 30, "max_spread_points": 50 } },
    { "name": "XAGUSD", "enabled": false }
  ]
}
"""


def _write(tmp_path, text):
    p = tmp_path / "config.json"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _mutated(**changes):
    data = json.loads(EXAMPLE_JSON)
    for key, value in changes.items():
        data[key] = value
    return json.dumps(data)


def test_load_config_applies_per_symbol_overrides(tmp_path):
    cfg = load_config(_write(tmp_path, EXAMPLE_JSON))
    xau = next(s for s in cfg.symbols if s.name == "XAUUSD")
    assert xau.strategy.or_minutes == 30  # override
    assert xau.strategy.max_spread_points == 50  # override
    assert xau.strategy.target_r == 2.0  # inherited top-level


def test_symbols_without_overrides_inherit_top_level(tmp_path):
    cfg = load_config(_write(tmp_path, EXAMPLE_JSON))
    eur = next(s for s in cfg.symbols if s.name == "EURUSD")
    assert eur.strategy.or_minutes == 15
    assert eur.strategy.stop_rule == "or_mid"
    assert eur.strategy.allow_short is True
    assert eur.risk.risk_per_trade_pct == 1.0
    assert eur.risk.max_weekly_loss_pct == 6.0
    assert eur.session.timezone == "Europe/London"
    assert eur.session.open == "08:00"
    assert eur.session.flat_by == "20:00"


def test_enabled_flag_and_timemachine(tmp_path):
    cfg = load_config(_write(tmp_path, EXAMPLE_JSON))
    assert cfg.timeframe == "M5"
    assert [s.enabled for s in cfg.symbols] == [True, True, True, False]
    assert cfg.timemachine.enabled is False
    assert cfg.timemachine.min_p_green == 0.5
    assert cfg.timemachine.replays == 10000
    assert cfg.timemachine.seed == 19


def test_overrides_can_target_risk_and_session(tmp_path):
    data = json.loads(EXAMPLE_JSON)
    data["symbols"][0]["overrides"] = {
        "risk_per_trade_pct": 0.5,
        "flat_by": "18:00",
        "stop_rule": "atr",
    }
    cfg = load_config(_write(tmp_path, json.dumps(data)))
    eur = cfg.symbols[0]
    gbp = cfg.symbols[1]
    assert eur.risk.risk_per_trade_pct == 0.5
    assert eur.risk.max_daily_loss_pct == 3.0
    assert eur.session.flat_by == "18:00"
    assert eur.session.open == "08:00"
    assert eur.strategy.stop_rule == "atr"
    assert gbp.risk.risk_per_trade_pct == 1.0  # other symbols unaffected


def test_load_config_rejects_unknown_stop_rule(tmp_path):
    data = json.loads(EXAMPLE_JSON)
    data["strategy"]["stop_rule"] = "bogus"
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, json.dumps(data)))


def test_load_config_rejects_unknown_stop_rule_in_override(tmp_path):
    data = json.loads(EXAMPLE_JSON)
    data["symbols"][0]["overrides"] = {"stop_rule": "bogus"}
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, json.dumps(data)))


def test_load_config_rejects_non_m5_timeframe(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, _mutated(timeframe="M15")))


def test_load_config_rejects_empty_symbol_name(tmp_path):
    data = json.loads(EXAMPLE_JSON)
    data["symbols"][0]["name"] = "  "
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, json.dumps(data)))


def test_load_settings_reads_mt5_keys(monkeypatch):
    monkeypatch.setenv("MT5_LOGIN", "12345")
    monkeypatch.setenv("MT5_PASSWORD", "pw")
    monkeypatch.setenv("MT5_SERVER", "Demo-Server")
    monkeypatch.delenv("DB_PATH", raising=False)
    s = load_settings()
    assert s.mt5_login == 12345
    assert s.mt5_password == "pw"
    assert s.mt5_server == "Demo-Server"
    assert s.db_path == "data/fxbot.db"


def test_load_settings_missing_keys_raises(monkeypatch):
    monkeypatch.delenv("MT5_LOGIN", raising=False)
    monkeypatch.setenv("MT5_PASSWORD", "pw")
    monkeypatch.setenv("MT5_SERVER", "x")
    with pytest.raises(ValueError):
        load_settings()


def _cfg_with(tmp_path, mutate):
    data = json.loads(EXAMPLE_JSON)
    mutate(data)
    return _write(tmp_path, json.dumps(data))


def test_example_config_loads():
    cfg = load_config("config.example.json")
    xau = next(s for s in cfg.symbols if s.name == "XAUUSD")
    assert xau.strategy.or_minutes == 30
    assert xau.strategy.target_r == 2.0


@pytest.mark.parametrize("bad", ["false", "no", "0", 0, 1, None])
def test_enabled_must_be_real_bool(tmp_path, bad):
    path = _cfg_with(tmp_path, lambda d: d["symbols"][0].__setitem__("enabled", bad))
    with pytest.raises(ValueError):
        load_config(path)


def test_allow_short_string_rejected(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["strategy"].__setitem__("allow_short", "false"))
    with pytest.raises(ValueError):
        load_config(path)


def test_or_minutes_string_rejected(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["strategy"].__setitem__("or_minutes", "15"))
    with pytest.raises(ValueError):
        load_config(path)


def test_numeric_field_rejects_bool_and_float_for_int(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["risk"].__setitem__("max_trades_per_day", True))
    with pytest.raises(ValueError):
        load_config(path)
    path = _cfg_with(tmp_path, lambda d: d["strategy"].__setitem__("or_minutes", 15.5))
    with pytest.raises(ValueError):
        load_config(path)


def test_wrong_type_in_override_rejected(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", {"or_minutes": "30"}))
    with pytest.raises(ValueError):
        load_config(path)
    path = _cfg_with(
        tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", {"strategy": {"allow_short": "no"}})
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_timemachine_enabled_must_be_bool(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["timemachine_filter"].__setitem__("enabled", "false"))
    with pytest.raises(ValueError):
        load_config(path)


def test_unknown_key_in_block_rejected(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["strategy"].__setitem__("or_minuts", 15))
    with pytest.raises(ValueError, match="or_minuts"):
        load_config(path)


def test_unknown_override_key_rejected(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", {"or_minuts": 30}))
    with pytest.raises(ValueError, match="or_minuts"):
        load_config(path)


def test_unknown_key_in_grouped_override_rejected(tmp_path):
    path = _cfg_with(
        tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", {"strategy": {"or_minuts": 30}})
    )
    with pytest.raises(ValueError, match="or_minuts"):
        load_config(path)


def test_grouped_by_block_overrides(tmp_path):
    path = _cfg_with(
        tmp_path,
        lambda d: d["symbols"][0].__setitem__(
            "overrides",
            {"strategy": {"or_minutes": 45}, "risk": {"risk_per_trade_pct": 0.25}, "session": {"flat_by": "17:00"}},
        ),
    )
    cfg = load_config(path)
    eur, gbp = cfg.symbols[0], cfg.symbols[1]
    assert eur.strategy.or_minutes == 45
    assert eur.strategy.target_r == 2.0  # inherited
    assert eur.risk.risk_per_trade_pct == 0.25
    assert eur.session.flat_by == "17:00"
    assert gbp.strategy.or_minutes == 15  # other symbol unaffected


def test_grouped_override_block_must_be_object(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", {"strategy": 5}))
    with pytest.raises(ValueError):
        load_config(path)


def test_missing_symbols_gives_empty_list(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d.pop("symbols"))
    assert load_config(path).symbols == []


def test_symbols_must_be_a_list(tmp_path):
    path = _cfg_with(tmp_path, lambda d: d.__setitem__("symbols", {"name": "EURUSD"}))
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize("bad", [[], "x", 5, ["a"]])
def test_non_dict_overrides_rejected(tmp_path, bad):
    path = _cfg_with(tmp_path, lambda d: d["symbols"][0].__setitem__("overrides", bad))
    with pytest.raises(ValueError):
        load_config(path)
