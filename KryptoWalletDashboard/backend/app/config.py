from dataclasses import dataclass
from datetime import datetime, timezone
import os

from dotenv import load_dotenv

from app import env_file

load_dotenv(env_file.ENV_FILE_PATH)


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


def _load_all_from_env() -> None:
    """Assign every hot-reloadable config constant from the current
    os.environ. Called once at import time below, and again by
    reload_config() after re-reading the .env file -- reassigning these
    module-level names is what makes every existing `config.<NAME>`
    attribute access (e.g. app.adapters.factory) see fresh values on its
    very next read, with no process restart."""
    global BITCOIN_WALLETS, BITCOIN_XPUBS, ETHEREUM_WALLETS, ETHERSCAN_API_KEY
    global SOLANA_WALLETS, CARDANO_WALLETS, CARDANO_STAKE_WALLETS, VECHAIN_WALLETS
    global KRAKEN_API_KEY, KRAKEN_API_SECRET
    global COINBASE_API_KEY_NAME, COINBASE_API_PRIVATE_KEY
    global MEXC_API_KEY, MEXC_API_SECRET, MEXC_TRADING_PAIRS
    global BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_TRADING_PAIRS, BINANCE_SYNC_START

    BITCOIN_WALLETS = parse_wallets(os.getenv("BITCOIN_ADDRESSES"))
    BITCOIN_XPUBS = parse_wallets(os.getenv("BITCOIN_XPUBS"))
    ETHEREUM_WALLETS = parse_wallets(os.getenv("ETHEREUM_ADDRESSES"))
    ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
    SOLANA_WALLETS = parse_wallets(os.getenv("SOLANA_ADDRESSES"))
    CARDANO_WALLETS = parse_wallets(os.getenv("CARDANO_ADDRESSES"))
    CARDANO_STAKE_WALLETS = parse_wallets(os.getenv("CARDANO_STAKE_ADDRESSES"))
    VECHAIN_WALLETS = parse_wallets(os.getenv("VECHAIN_ADDRESSES"))
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


_load_all_from_env()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./krypto_dashboard.db")


def reload_config(path: str | None = None) -> None:
    """Re-read the .env file and refresh every hot-reloadable config value
    in place. `override=True` is required: python-dotenv's load_dotenv()
    otherwise only sets environment variables that aren't already present
    in os.environ, silently ignoring a changed value for one that's
    already loaded (which every value here already is, from the initial
    load_dotenv() call above at import time).

    DATABASE_URL is deliberately not touched here -- see its comment
    above; reloading it would silently do nothing since the SQLAlchemy
    engine is already built from whatever it was at process start.

    `path` defaults to `env_file.ENV_FILE_PATH`, looked up as a live
    attribute on the `env_file` module (`import app.env_file as env_file`
    above, not `from app.env_file import ENV_FILE_PATH`) rather than a
    name copied into this module's namespace at import time. A copied
    name would freeze the value as of config.py's own import, so any
    later `monkeypatch.setattr("app.env_file.ENV_FILE_PATH", ...)` --
    exactly how tests point this whole module at a temp file -- would
    have no effect here even though it correctly redirects
    read_config_values/write_config_values in env_file.py itself.
    """
    load_dotenv(path or env_file.ENV_FILE_PATH, override=True)
    _load_all_from_env()
