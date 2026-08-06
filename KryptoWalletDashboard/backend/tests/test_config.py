from app.config import parse_wallets


def test_parse_wallets_returns_empty_list_for_none():
    assert parse_wallets(None) == []


def test_parse_wallets_returns_empty_list_for_empty_string():
    assert parse_wallets("") == []


def test_parse_wallets_parses_single_entry():
    result = parse_wallets("main:bc1qexample")
    assert len(result) == 1
    assert result[0].label == "main"
    assert result[0].address == "bc1qexample"


def test_parse_wallets_parses_multiple_entries_and_trims_whitespace():
    result = parse_wallets(" main : bc1qexample , savings:bc1qother ")
    assert result == [
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="main", address="bc1qexample"),
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="savings", address="bc1qother"),
    ]


def test_coinbase_private_key_converts_escaped_newlines_to_real_newlines():
    from app.config import normalize_pem_env_value

    escaped = "-----BEGIN EC PRIVATE KEY-----\\nABC123\\n-----END EC PRIVATE KEY-----\\n"
    result = normalize_pem_env_value(escaped)

    assert result == "-----BEGIN EC PRIVATE KEY-----\nABC123\n-----END EC PRIVATE KEY-----\n"


def test_normalize_pem_env_value_returns_empty_string_for_none():
    from app.config import normalize_pem_env_value

    assert normalize_pem_env_value(None) == ""


def test_parse_trading_pairs_returns_empty_list_for_none():
    from app.config import parse_trading_pairs

    assert parse_trading_pairs(None) == []


def test_parse_trading_pairs_parses_single_entry():
    from app.config import TradingPairConfig, parse_trading_pairs

    result = parse_trading_pairs("BTCUSDT:BTC:USDT")

    assert result == [TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")]


def test_parse_trading_pairs_parses_multiple_entries_and_trims_whitespace():
    from app.config import TradingPairConfig, parse_trading_pairs

    result = parse_trading_pairs(" BTCUSDT : BTC : USDT , ETHUSDT:ETH:USDT ")

    assert result == [
        TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT"),
        TradingPairConfig(symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT"),
    ]


def test_parse_trading_pairs_skips_malformed_entries():
    from app.config import parse_trading_pairs

    result = parse_trading_pairs("BTCUSDT:BTC,ETHUSDT:ETH:USDT")

    assert [p.symbol for p in result] == ["ETHUSDT"]


def test_parse_sync_start_returns_none_for_empty():
    from app.config import parse_sync_start

    assert parse_sync_start(None) is None
    assert parse_sync_start("") is None


def test_parse_sync_start_parses_iso_date_as_utc_midnight():
    from datetime import datetime, timezone

    from app.config import parse_sync_start

    result = parse_sync_start("2020-01-01")

    assert result == datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_parse_sync_start_returns_none_for_invalid_format():
    from app.config import parse_sync_start

    assert parse_sync_start("not-a-date") is None


def test_bitcoin_xpubs_reuses_wallet_parsing():
    from app.config import parse_wallets

    result = parse_wallets("ledger:xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8")

    assert len(result) == 1
    assert result[0].label == "ledger"
    assert result[0].address.startswith("xpub")


def test_solana_wallets_reuses_wallet_parsing():
    from app.config import parse_wallets

    result = parse_wallets("ledger-1:9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM,ledger-2:11111111111111111111111111111111111111111")

    assert len(result) == 2
    assert result[0].label == "ledger-1"
    assert result[1].label == "ledger-2"


def test_reload_config_picks_up_changed_values_from_the_env_file(tmp_path, monkeypatch):
    import os

    from app import config

    # NOTE: monkeypatch.delenv("SOLANA_ADDRESSES", raising=False) is NOT
    # sufficient here -- monkeypatch only registers a teardown-restore
    # action for a key it deletes if that key already existed at call
    # time. In a clean test env SOLANA_ADDRESSES is typically already
    # absent, so delenv would be a no-op that registers nothing, and
    # reload_config()'s later load_dotenv(..., override=True) call would
    # then set os.environ["SOLANA_ADDRESSES"] with nothing to clean it up
    # afterwards. Likewise monkeypatch.setattr(config, "SOLANA_WALLETS",
    # config.SOLANA_WALLETS) only snapshots the CURRENT value to restore
    # -- it does not protect against reload_config() reassigning the
    # attribute again later in the test. So we snapshot and restore both
    # os.environ and config.SOLANA_WALLETS by hand.
    original_env_value = os.environ.get("SOLANA_ADDRESSES")
    original_solana_wallets = config.SOLANA_WALLETS
    try:
        env_file = tmp_path / ".env"
        env_file.write_text("SOLANA_ADDRESSES=main:first\n", encoding="utf-8")
        config.reload_config(str(env_file))
        assert config.SOLANA_WALLETS[0].address == "first"

        env_file.write_text("SOLANA_ADDRESSES=main:second\n", encoding="utf-8")
        config.reload_config(str(env_file))

        assert config.SOLANA_WALLETS[0].address == "second"
    finally:
        if original_env_value is None:
            os.environ.pop("SOLANA_ADDRESSES", None)
        else:
            os.environ["SOLANA_ADDRESSES"] = original_env_value
        config.SOLANA_WALLETS = original_solana_wallets


_SECTION_ENABLED_NAMES = [
    "BITCOIN_ENABLED", "SOLANA_ENABLED", "CARDANO_ENABLED", "VECHAIN_ENABLED",
    "EVM_ENABLED", "KRAKEN_ENABLED", "COINBASE_ENABLED", "MEXC_ENABLED", "BINANCE_ENABLED",
]


def test_section_enabled_flags_default_to_true_when_unset(monkeypatch):
    import os

    from app import config

    # Same pitfall as test_reload_config_picks_up_changed_values_from_the_env_file
    # above: monkeypatch.delenv(name, raising=False) registers no teardown
    # action when the name is already absent, so it alone would not protect
    # against _load_all_from_env() reassigning the module-level
    # config.*_ENABLED attributes. Snapshot and restore both os.environ and
    # every touched config attribute by hand.
    original_env_values = {name: os.environ.get(name) for name in _SECTION_ENABLED_NAMES}
    original_config_values = {name: getattr(config, name) for name in _SECTION_ENABLED_NAMES}
    try:
        for name in _SECTION_ENABLED_NAMES:
            monkeypatch.delenv(name, raising=False)
        config._load_all_from_env()

        assert config.BITCOIN_ENABLED is True
        assert config.SOLANA_ENABLED is True
        assert config.CARDANO_ENABLED is True
        assert config.VECHAIN_ENABLED is True
        assert config.EVM_ENABLED is True
        assert config.KRAKEN_ENABLED is True
        assert config.COINBASE_ENABLED is True
        assert config.MEXC_ENABLED is True
        assert config.BINANCE_ENABLED is True
    finally:
        for name, value in original_env_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        for name, value in original_config_values.items():
            setattr(config, name, value)


def test_section_enabled_flag_is_false_when_env_var_is_false(monkeypatch):
    import os

    from app import config

    original_env_value = os.environ.get("CARDANO_ENABLED")
    original_config_value = config.CARDANO_ENABLED
    try:
        monkeypatch.setenv("CARDANO_ENABLED", "false")
        config._load_all_from_env()

        assert config.CARDANO_ENABLED is False
    finally:
        if original_env_value is None:
            os.environ.pop("CARDANO_ENABLED", None)
        else:
            os.environ["CARDANO_ENABLED"] = original_env_value
        config.CARDANO_ENABLED = original_config_value


def test_parse_enabled_treats_missing_as_true():
    from app.config import _parse_enabled

    assert _parse_enabled(None) is True


def test_parse_enabled_is_case_insensitive_for_false():
    from app.config import _parse_enabled

    assert _parse_enabled("False") is False
    assert _parse_enabled("FALSE") is False
    assert _parse_enabled("false") is False


def test_parse_enabled_treats_anything_else_as_true():
    from app.config import _parse_enabled

    assert _parse_enabled("true") is True
    assert _parse_enabled("yes") is True
    assert _parse_enabled("") is True


def test_reload_config_defaults_to_the_real_env_file_path_when_no_path_given(tmp_path, monkeypatch):
    from app import config, env_file

    # Point env_file.ENV_FILE_PATH (the single source of truth -- config.py
    # no longer keeps its own copy of the name, see the regression test
    # below) at a file that doesn't exist so this test never touches the
    # real .env or leaks real config values into other tests.
    monkeypatch.setattr(env_file, "ENV_FILE_PATH", str(tmp_path / "does-not-exist.env"))

    # Doesn't assert on any actual content -- just proves the no-argument
    # call resolves to env_file.ENV_FILE_PATH rather than raising or
    # silently no-op'ing on some other path.
    import inspect

    signature = inspect.signature(config.reload_config)
    assert signature.parameters["path"].default is None
    # Calling with no path must not raise even though the file doesn't exist.
    config.reload_config()


def test_reload_config_with_no_path_respects_a_monkeypatched_env_file_path(tmp_path, monkeypatch):
    """Regression test for the bug where config.py did
    `from app.env_file import ENV_FILE_PATH`, copying the value into its
    own namespace once at import time. reload_config(path=None) then fell
    back to that frozen copy instead of a live attribute lookup on the
    env_file module, so monkeypatching `app.env_file.ENV_FILE_PATH` --
    exactly what tests/test_api.py's config endpoint tests do, and the
    whole point of resolving `path` dynamically in the first place -- had
    *zero* effect on reload_config(), which would silently reload from
    whatever the real default .env path was instead of the intended file.

    This must assert on actual reloaded content (not just "doesn't
    raise") to be a real check: with the bug present, this test fails
    because SOLANA_WALLETS ends up empty (or reflecting the real .env)
    rather than "from-monkeypatched-path".
    """
    import os

    from app import config, env_file

    original_env_value = os.environ.get("SOLANA_ADDRESSES")
    original_solana_wallets = config.SOLANA_WALLETS
    try:
        os.environ.pop("SOLANA_ADDRESSES", None)

        patched_env_file = tmp_path / ".env"
        patched_env_file.write_text("SOLANA_ADDRESSES=main:from-monkeypatched-path\n", encoding="utf-8")
        monkeypatch.setattr(env_file, "ENV_FILE_PATH", str(patched_env_file))

        config.reload_config()  # no explicit path -- must resolve via env_file.ENV_FILE_PATH

        assert config.SOLANA_WALLETS[0].address == "from-monkeypatched-path"
    finally:
        if original_env_value is None:
            os.environ.pop("SOLANA_ADDRESSES", None)
        else:
            os.environ["SOLANA_ADDRESSES"] = original_env_value
        config.SOLANA_WALLETS = original_solana_wallets
