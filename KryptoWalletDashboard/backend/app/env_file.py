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
_KNOWN_FIELD_NAMES = {f.name for f in CONFIG_FIELDS}

SECTION_TOGGLE_ENV_VAR: dict[str, str] = {
    "Bitcoin": "BITCOIN_ENABLED",
    "Solana": "SOLANA_ENABLED",
    "Cardano": "CARDANO_ENABLED",
    "VeChain": "VECHAIN_ENABLED",
    "Ethereum & EVM-Chains": "EVM_ENABLED",
    "Kraken": "KRAKEN_ENABLED",
    "Coinbase": "COINBASE_ENABLED",
    "MEXC": "MEXC_ENABLED",
    "Binance": "BINANCE_ENABLED",
}


class InvalidConfigValueError(ValueError):
    """Raised for a config write request that must not be silently
    accepted: an unknown field/section name, or a value containing a
    literal newline or carriage return.

    A literal newline in a value would let the line-based .env writer be
    tricked into emitting an extra "line" -- effectively letting one
    field's submitted value inject an arbitrary, unrelated key=value
    assignment (including overwriting a *different* field, such as a
    secret) into the file. Multi-line values (e.g. the Coinbase PEM
    private key) are always represented in .env with escaped `\\n`
    *sequences*, never real newlines -- see app.config.normalize_pem_env_value,
    which converts them back on read. So rejecting a raw newline here
    doesn't break any legitimate value.
    """


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


def read_config_values(path: str | None = None) -> dict[str, str]:
    """Current value per known field, read directly from the .env file
    (not os.environ -- this must reflect the file even before the running
    process has reloaded). Secret fields are always "" regardless of what
    is actually stored: the real value never reaches the frontend.

    `path` defaults to the *current* value of the module-level
    ENV_FILE_PATH, resolved when this function is called rather than when
    it was defined -- a plain `path: str = ENV_FILE_PATH` default would
    capture the value once at import time, so callers (and tests) that
    monkeypatch `app.env_file.ENV_FILE_PATH` afterwards would be silently
    ignored.
    """
    raw = _read_raw_values(path if path is not None else ENV_FILE_PATH)
    return {
        field.name: ("" if field.is_secret else raw.get(field.name, ""))
        for field in CONFIG_FIELDS
    }


def _write_raw_updates(effective_updates: dict[str, str], path: str) -> None:
    """Shared line-rewriting primitive for both write_config_values and
    write_section_toggles: replaces matching `KEY=...` lines in place,
    preserving every other line (comments, unrelated variables)
    untouched, and appends any key not already present. Callers are
    responsible for their own key/value validation before calling this --
    it does no validation itself.
    """
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


def read_section_toggles(path: str | None = None) -> dict[str, bool]:
    """Enabled/disabled state per section, read directly from the .env
    file. A missing env var means enabled -- see app.config._parse_enabled
    for the identical convention applied when the running process loads
    its config, and the design doc for why (opt-out, not opt-in: an
    existing user's already-configured sections must keep working
    without any action on their part after this feature ships)."""
    raw = _read_raw_values(path if path is not None else ENV_FILE_PATH)
    return {
        section: raw.get(env_var, "true").strip().lower() != "false"
        for section, env_var in SECTION_TOGGLE_ENV_VAR.items()
    }


def write_section_toggles(updates: dict[str, bool], path: str | None = None) -> None:
    """updates: section name (e.g. "Bitcoin") -> desired enabled state."""
    unknown = set(updates) - set(SECTION_TOGGLE_ENV_VAR)
    if unknown:
        raise InvalidConfigValueError(f"Unknown section(s): {', '.join(sorted(unknown))}")

    env_updates = {
        SECTION_TOGGLE_ENV_VAR[section]: ("true" if enabled else "false")
        for section, enabled in updates.items()
    }
    _write_raw_updates(env_updates, path if path is not None else ENV_FILE_PATH)


def write_config_values(updates: dict[str, str], path: str | None = None) -> None:
    """Apply `updates` (field name -> new value) to the .env file in
    place, preserving every other line (comments, unrelated variables)
    untouched.

    A SECRET field's empty string means "leave the existing stored value
    unchanged" (the UI never shows secrets, so an empty submission isn't
    a deliberate clear). Every other field's empty string is a deliberate
    clear -- the UI does show the current value, so the user seeing and
    blanking it is intentional.

    See `read_config_values` above for why `path` defaults to `None` and
    is resolved against the current `ENV_FILE_PATH` inside the function
    body instead of as a literal default value.

    Raises InvalidConfigValueError -- before touching the file -- for any
    update whose key isn't a known CONFIG_FIELDS name, or whose value
    contains a literal "\\n" or "\\r".
    """
    for name, value in updates.items():
        if name not in _KNOWN_FIELD_NAMES:
            raise InvalidConfigValueError(f"Unknown config field: {name!r}")
        if "\n" in value or "\r" in value:
            raise InvalidConfigValueError(
                f"Value for {name!r} must not contain a newline or carriage-return character"
            )

    effective_updates = {
        name: value
        for name, value in updates.items()
        if not (name in _SECRET_FIELD_NAMES and value == "")
    }
    _write_raw_updates(effective_updates, path if path is not None else ENV_FILE_PATH)
