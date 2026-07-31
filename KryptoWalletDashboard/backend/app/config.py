from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class WalletConfig:
    label: str
    address: str


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


def normalize_pem_env_value(env_value: str | None) -> str:
    """PEM private keys are multi-line; when stored in a .env file they're
    typically written with literal backslash-n sequences instead of real
    newlines. Convert those back to real newlines so the value is usable
    directly as a PEM string."""
    if not env_value:
        return ""
    return env_value.replace("\\n", "\n")


BITCOIN_WALLETS = parse_wallets(os.getenv("BITCOIN_ADDRESSES"))
ETHEREUM_WALLETS = parse_wallets(os.getenv("ETHEREUM_ADDRESSES"))
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
COINBASE_API_KEY_NAME = os.getenv("COINBASE_API_KEY_NAME", "")
COINBASE_API_PRIVATE_KEY = normalize_pem_env_value(os.getenv("COINBASE_API_PRIVATE_KEY"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./krypto_dashboard.db")
