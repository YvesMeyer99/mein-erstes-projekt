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


BITCOIN_WALLETS = parse_wallets(os.getenv("BITCOIN_ADDRESSES"))
ETHEREUM_WALLETS = parse_wallets(os.getenv("ETHEREUM_ADDRESSES"))
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./krypto_dashboard.db")
