from app import config
from app.adapters.base import TransactionAdapter
from app.adapters.binance import BinanceAdapter
from app.adapters.bitcoin import BitcoinAdapter
from app.adapters.bitcoin_xpub import BitcoinXpubAdapter
from app.adapters.cardano import CardanoAdapter, CardanoStakeAdapter
from app.adapters.coinbase import CoinbaseAdapter
from app.adapters.evm import EvmAdapter
from app.adapters.evm_chains import EVM_CHAINS
from app.adapters.kraken import KrakenAdapter
from app.adapters.mexc import MexcAdapter
from app.adapters.solana import SolanaAdapter
from app.adapters.vechain import VeChainAdapter


def build_adapters_from_config() -> list[TransactionAdapter]:
    adapters: list[TransactionAdapter] = []
    for wallet in config.BITCOIN_WALLETS:
        adapters.append(BitcoinAdapter(account_label=wallet.label, address=wallet.address))
    for wallet in config.BITCOIN_XPUBS:
        adapters.append(BitcoinXpubAdapter(account_label=wallet.label, extended_key=wallet.address))
    for wallet in config.SOLANA_WALLETS:
        adapters.append(SolanaAdapter(account_label=wallet.label, address=wallet.address))
    for wallet in config.CARDANO_WALLETS:
        adapters.append(CardanoAdapter(account_label=wallet.label, address=wallet.address))
    for wallet in config.CARDANO_STAKE_WALLETS:
        adapters.append(CardanoStakeAdapter(account_label=wallet.label, stake_address=wallet.address))
    for wallet in config.VECHAIN_WALLETS:
        adapters.append(VeChainAdapter(account_label=wallet.label, address=wallet.address))
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
    if config.COINBASE_API_KEY_NAME and config.COINBASE_API_PRIVATE_KEY:
        adapters.append(
            CoinbaseAdapter(
                account_label="coinbase-main",
                api_key_name=config.COINBASE_API_KEY_NAME,
                private_key_pem=config.COINBASE_API_PRIVATE_KEY,
            )
        )
    if config.MEXC_API_KEY and config.MEXC_API_SECRET:
        adapters.append(
            MexcAdapter(
                account_label="mexc-main",
                api_key=config.MEXC_API_KEY,
                api_secret=config.MEXC_API_SECRET,
                trading_pairs=config.MEXC_TRADING_PAIRS,
            )
        )
    if config.BINANCE_API_KEY and config.BINANCE_API_SECRET:
        adapters.append(
            BinanceAdapter(
                account_label="binance-main",
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                trading_pairs=config.BINANCE_TRADING_PAIRS,
                sync_start=config.BINANCE_SYNC_START,
            )
        )
    return adapters
