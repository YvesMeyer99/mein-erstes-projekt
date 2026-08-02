import os
from dataclasses import dataclass

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE_PATH = os.path.join(_BACKEND_DIR, ".env")


@dataclass(frozen=True)
class ConfigField:
    name: str
    section: str
    label: str
    is_secret: bool
    hint: str = ""


# Single source of truth for what the Konfiguration page shows and edits.
# DATABASE_URL is deliberately excluded -- it only takes effect at process
# start (SQLAlchemy engine creation in app.db), so exposing it here would
# be misleading (editing it would silently do nothing until a restart).
CONFIG_FIELDS: list[ConfigField] = [
    ConfigField("BITCOIN_ADDRESSES", "Bitcoin", "Einzelne Adressen", False, "label:adresse, kommagetrennt"),
    ConfigField("BITCOIN_XPUBS", "Bitcoin", "HD-Wallet (xpub/zpub)", False, "label:zpub..., kommagetrennt"),
    ConfigField("SOLANA_ADDRESSES", "Solana", "Adressen", False, "label:adresse, kommagetrennt"),
    ConfigField("CARDANO_ADDRESSES", "Cardano", "Einzelne Adressen", False, "label:addr1..., kommagetrennt"),
    ConfigField("CARDANO_STAKE_ADDRESSES", "Cardano", "Stake-Adressen", False, "label:stake1..., kommagetrennt"),
    ConfigField("VECHAIN_ADDRESSES", "VeChain", "Adressen", False, "label:0x..., kommagetrennt"),
    ConfigField("ETHEREUM_ADDRESSES", "Ethereum & EVM-Chains", "Adressen", False, "label:0x..., kommagetrennt"),
    ConfigField("ETHERSCAN_API_KEY", "Ethereum & EVM-Chains", "Etherscan API-Key", False, ""),
    ConfigField("KRAKEN_API_KEY", "Kraken", "API-Key", False, ""),
    ConfigField("KRAKEN_API_SECRET", "Kraken", "API-Secret", True, "Nur read-only Keys verwenden"),
    ConfigField("COINBASE_API_KEY_NAME", "Coinbase", "API-Key-Name", False, ""),
    ConfigField("COINBASE_API_PRIVATE_KEY", "Coinbase", "Private Key (PEM)", True, ""),
    ConfigField("MEXC_API_KEY", "MEXC", "API-Key", False, ""),
    ConfigField("MEXC_API_SECRET", "MEXC", "API-Secret", True, ""),
    ConfigField("MEXC_TRADING_PAIRS", "MEXC", "Trading-Paare", False, "SYMBOL:BASE:QUOTE, kommagetrennt"),
    ConfigField("BINANCE_API_KEY", "Binance", "API-Key", False, ""),
    ConfigField("BINANCE_API_SECRET", "Binance", "API-Secret", True, ""),
    ConfigField("BINANCE_TRADING_PAIRS", "Binance", "Trading-Paare", False, "SYMBOL:BASE:QUOTE, kommagetrennt"),
    ConfigField("BINANCE_SYNC_START", "Binance", "Sync-Start-Datum", False, "YYYY-MM-DD"),
]

_SECRET_FIELD_NAMES = {f.name for f in CONFIG_FIELDS if f.is_secret}


def _read_raw_values(path: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def read_config_values(path: str = ENV_FILE_PATH) -> dict[str, str]:
    """Current value per known field, read directly from the .env file
    (not os.environ -- this must reflect the file even before the running
    process has reloaded). Secret fields are always "" regardless of what
    is actually stored: the real value never reaches the frontend."""
    raw = _read_raw_values(path)
    return {
        field.name: ("" if field.is_secret else raw.get(field.name, ""))
        for field in CONFIG_FIELDS
    }


def write_config_values(updates: dict[str, str], path: str = ENV_FILE_PATH) -> None:
    """Apply `updates` (field name -> new value) to the .env file in
    place, preserving every other line (comments, unrelated variables)
    untouched.

    A SECRET field's empty string means "leave the existing stored value
    unchanged" (the UI never shows secrets, so an empty submission isn't
    a deliberate clear). Every other field's empty string is a deliberate
    clear -- the UI does show the current value, so the user seeing and
    blanking it is intentional.
    """
    effective_updates = {
        name: value
        for name, value in updates.items()
        if not (name in _SECRET_FIELD_NAMES and value == "")
    }
    if not effective_updates:
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in effective_updates:
                new_lines.append(f"{key}={effective_updates[key]}\n")
                seen.add(key)
                continue
        new_lines.append(line)

    remaining = [name for name in effective_updates if name not in seen]
    if remaining:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        for name in remaining:
            new_lines.append(f"{name}={effective_updates[name]}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
