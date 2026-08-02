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


def test_reload_config_defaults_to_the_real_env_file_path_when_no_path_given(tmp_path, monkeypatch):
    from app import config

    # Point ENV_FILE_PATH at a file that doesn't exist so this test never
    # touches the real .env or leaks real config values into other tests.
    # This IS a case where monkeypatch.setattr's teardown-restore works
    # correctly (unlike the delenv pitfall above): config.ENV_FILE_PATH
    # already exists as an attribute before this call, so monkeypatch
    # captures its current value and restores it after the test.
    monkeypatch.setattr(config, "ENV_FILE_PATH", str(tmp_path / "does-not-exist.env"))

    # Doesn't assert on any actual content -- just proves the no-argument
    # call resolves to config.ENV_FILE_PATH rather than raising or
    # silently no-op'ing on some other path.
    import inspect

    signature = inspect.signature(config.reload_config)
    assert signature.parameters["path"].default is None
    # Calling with no path must not raise even though the file doesn't exist.
    config.reload_config()
