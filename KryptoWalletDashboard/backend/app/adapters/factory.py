from app import config
from app.adapters.base import TransactionAdapter
from app.adapters.bitcoin import BitcoinAdapter
from app.adapters.evm import EvmAdapter
from app.adapters.evm_chains import EVM_CHAINS
from app.adapters.kraken import KrakenAdapter


def build_adapters_from_config() -> list[TransactionAdapter]:
    adapters: list[TransactionAdapter] = []
    for wallet in config.BITCOIN_WALLETS:
        adapters.append(BitcoinAdapter(account_label=wallet.label, address=wallet.address))
    for wallet in config.ETHEREUM_WALLETS:
        for chain in EVM_CHAINS:
            adapters.append(
                EvmAdapter(
                    account_label=wallet.label,
                    address=wallet.address,
                    api_key=config.ETHERSCAN_API_KEY,
                    chain_id=chain.chain_id,
                    chain_name=chain.chain_name,
                    native_asset=chain.native_asset,
                )
            )
    if config.KRAKEN_API_KEY and config.KRAKEN_API_SECRET:
        adapters.append(
            KrakenAdapter(
                account_label="kraken-main",
                api_key=config.KRAKEN_API_KEY,
                api_secret=config.KRAKEN_API_SECRET,
            )
        )
    return adapters
