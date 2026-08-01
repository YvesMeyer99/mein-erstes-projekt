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
