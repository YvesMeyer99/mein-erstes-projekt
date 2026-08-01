import pytest

from app import config
from app.adapters.evm import EvmAdapter
from app.adapters.evm_chains import EVM_CHAINS
from app.adapters.factory import build_adapters_from_config


@pytest.fixture()
def one_wallet_config(monkeypatch):
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(
        config, "ETHEREUM_WALLETS", [config.WalletConfig(label="main", address="0xabc")]
    )
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "key")
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")


@pytest.fixture()
def two_wallet_config(monkeypatch):
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(
        config,
        "ETHEREUM_WALLETS",
        [
            config.WalletConfig(label="main", address="0xabc"),
            config.WalletConfig(label="savings", address="0xdef"),
        ],
    )
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "key")
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")


def test_one_ethereum_wallet_produces_one_evm_adapter_per_chain(one_wallet_config):
    adapters = build_adapters_from_config()

    evm_adapters = [a for a in adapters if isinstance(a, EvmAdapter)]
    assert len(evm_adapters) == len(EVM_CHAINS)
    assert {a.source_name for a in evm_adapters} == {c.chain_name for c in EVM_CHAINS}
    assert all(a.account_label == "main" for a in evm_adapters)
    assert all(a.address == "0xabc" for a in evm_adapters)


def test_two_ethereum_wallets_each_produce_one_evm_adapter_per_chain(two_wallet_config):
    adapters = build_adapters_from_config()

    evm_adapters = [a for a in adapters if isinstance(a, EvmAdapter)]
    assert len(evm_adapters) == 2 * len(EVM_CHAINS)

    main_adapters = [a for a in evm_adapters if a.account_label == "main"]
    savings_adapters = [a for a in evm_adapters if a.account_label == "savings"]
    assert len(main_adapters) == len(EVM_CHAINS)
    assert len(savings_adapters) == len(EVM_CHAINS)
    assert all(a.address == "0xabc" for a in main_adapters)
    assert all(a.address == "0xdef" for a in savings_adapters)
    assert {a.source_name for a in main_adapters} == {c.chain_name for c in EVM_CHAINS}
    assert {a.source_name for a in savings_adapters} == {c.chain_name for c in EVM_CHAINS}


def test_coinbase_adapter_is_added_when_configured(monkeypatch):
    from app.adapters.coinbase import CoinbaseAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "fake-pem")

    adapters = build_adapters_from_config()

    coinbase_adapters = [a for a in adapters if isinstance(a, CoinbaseAdapter)]
    assert len(coinbase_adapters) == 1
    assert coinbase_adapters[0].account_label == "coinbase-main"
    assert coinbase_adapters[0].api_key_name == "organizations/org/apiKeys/key"


def test_coinbase_adapter_is_not_added_when_only_partially_configured(monkeypatch):
    from app.adapters.coinbase import CoinbaseAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, CoinbaseAdapter) for a in adapters)


def test_mexc_adapter_is_added_when_configured(monkeypatch):
    from app.adapters.mexc import MexcAdapter
    from app.config import TradingPairConfig

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "key")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "secret")
    monkeypatch.setattr(
        config, "MEXC_TRADING_PAIRS", [TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")]
    )

    adapters = build_adapters_from_config()

    mexc_adapters = [a for a in adapters if isinstance(a, MexcAdapter)]
    assert len(mexc_adapters) == 1
    assert mexc_adapters[0].account_label == "mexc-main"
    assert mexc_adapters[0].trading_pairs[0].symbol == "BTCUSDT"


def test_mexc_adapter_is_not_added_when_only_partially_configured(monkeypatch):
    from app.adapters.mexc import MexcAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "key")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "MEXC_TRADING_PAIRS", [])

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, MexcAdapter) for a in adapters)


def test_binance_adapter_is_added_when_configured(monkeypatch):
    from app.adapters.binance import BinanceAdapter
    from app.config import TradingPairConfig

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "key")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "secret")
    monkeypatch.setattr(
        config, "BINANCE_TRADING_PAIRS", [TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")]
    )
    monkeypatch.setattr(config, "BINANCE_SYNC_START", None)

    adapters = build_adapters_from_config()

    binance_adapters = [a for a in adapters if isinstance(a, BinanceAdapter)]
    assert len(binance_adapters) == 1
    assert binance_adapters[0].account_label == "binance-main"
    assert binance_adapters[0].trading_pairs[0].symbol == "BTCUSDT"


def test_binance_adapter_is_not_added_when_only_partially_configured(monkeypatch):
    from app.adapters.binance import BinanceAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "key")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_TRADING_PAIRS", [])
    monkeypatch.setattr(config, "BINANCE_SYNC_START", None)

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BinanceAdapter) for a in adapters)


def test_bitcoin_xpub_adapter_is_added_for_each_configured_xpub(monkeypatch):
    from app.adapters.bitcoin_xpub import BitcoinXpubAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(
        config,
        "BITCOIN_XPUBS",
        [WalletConfig(label="ledger", address="xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8")],
    )
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    xpub_adapters = [a for a in adapters if isinstance(a, BitcoinXpubAdapter)]
    assert len(xpub_adapters) == 1
    assert xpub_adapters[0].account_label == "ledger"
    assert xpub_adapters[0].extended_key.startswith("xpub")


def test_no_bitcoin_xpub_adapters_when_none_configured(monkeypatch):
    from app.adapters.bitcoin_xpub import BitcoinXpubAdapter

    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BitcoinXpubAdapter) for a in adapters)


def test_solana_adapter_is_added_for_each_configured_address(monkeypatch):
    from app.adapters.solana import SolanaAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(
        config,
        "SOLANA_WALLETS",
        [WalletConfig(label="ledger-1", address="9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")],
    )
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    solana_adapters = [a for a in adapters if isinstance(a, SolanaAdapter)]
    assert len(solana_adapters) == 1
    assert solana_adapters[0].account_label == "ledger-1"
    assert solana_adapters[0].address == "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


def test_no_solana_adapters_when_none_configured(monkeypatch):
    from app.adapters.solana import SolanaAdapter

    monkeypatch.setattr(config, "SOLANA_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, SolanaAdapter) for a in adapters)
