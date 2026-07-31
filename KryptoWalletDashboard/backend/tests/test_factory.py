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
