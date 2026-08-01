from dataclasses import dataclass
from datetime import datetime, timezone
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class WalletConfig:
    label: str
    address: str


@dataclass(frozen=True)
class TradingPairConfig:
    symbol: str
    base_asset: str
    quote_asset: str


def parse_wallets(env_value: str | None) -> list[WalletConfig]:
    if not env_value:
        return []
    wallets = []
    for entry in env_value.split(","):
        label, _, address = entry.partition(":")
        label = label.strip()
        address = address.strip()
        if address:
            wallets.append(WalletConfig(label=label, address=address))
    return wallets


def parse_trading_pairs(env_value: str | None) -> list[TradingPairConfig]:
    if not env_value:
        return []
    pairs = []
    for entry in env_value.split(","):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        symbol, base_asset, quote_asset = (p.strip() for p in parts)
        if symbol and base_asset and quote_asset:
            pairs.append(TradingPairConfig(symbol=symbol, base_asset=base_asset, quote_asset=quote_asset))
    return pairs


def parse_sync_start(env_value: str | None) -> datetime | None:
    """Parse an optional 'YYYY-MM-DD' date string (e.g. Binance account
    creation date) into a UTC midnight datetime. Returns None if unset or
    malformed, in which case the caller falls back to its own default."""
    if not env_value:
        return None
    try:
        return datetime.strptime(env_value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def normalize_pem_env_value(env_value: str | None) -> str:
    """PEM private keys are multi-line; when stored in a .env file they're
    typically written with literal backslash-n sequences instead of real
    newlines. Convert those back to real newlines so the value is usable
    directly as a PEM string."""
    if not env_value:
        return ""
    return env_value.replace("\\n", "\n")


BITCOIN_WALLETS = parse_wallets(os.getenv("BITCOIN_ADDRESSES"))
BITCOIN_XPUBS = parse_wallets(os.getenv("BITCOIN_XPUBS"))
ETHEREUM_WALLETS = parse_wallets(os.getenv("ETHEREUM_ADDRESSES"))
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
SOLANA_WALLETS = parse_wallets(os.getenv("SOLANA_ADDRESSES"))
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
COINBASE_API_KEY_NAME = os.getenv("COINBASE_API_KEY_NAME", "")
COINBASE_API_PRIVATE_KEY = normalize_pem_env_value(os.getenv("COINBASE_API_PRIVATE_KEY"))
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")
MEXC_TRADING_PAIRS = parse_trading_pairs(os.getenv("MEXC_TRADING_PAIRS"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TRADING_PAIRS = parse_trading_pairs(os.getenv("BINANCE_TRADING_PAIRS"))
BINANCE_SYNC_START = parse_sync_start(os.getenv("BINANCE_SYNC_START"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./krypto_dashboard.db")
