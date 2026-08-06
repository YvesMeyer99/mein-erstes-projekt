# Per-Section Enable/Disable Toggles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a checkbox per section (Bitcoin, Solana, Cardano, VeChain, Ethereum & EVM-Chains, Kraken, Coinbase, MEXC, Binance) to the Konfiguration page. Unchecking a section means its wallets/API keys stay in `.env` (nothing is deleted) but that section's adapters are simply not built, so sync stops producing errors for a source the user isn't currently using — without losing the underlying configured values for later.

**Architecture:** One new boolean env var per section (e.g. `BITCOIN_ENABLED`), read via a new `_parse_enabled()` helper in `app/config.py` using **opt-out semantics**: a missing/unset var means enabled (`true`), so every existing user's current setup keeps working exactly as before this feature ships — only an explicit `false` disables a section. `app/adapters/factory.py` gates each section's adapter-building block behind its `config.<SECTION>_ENABLED` flag. `app/env_file.py` gets a small, DRY-refactored write path (`_write_raw_updates`, shared by the existing `write_config_values` and the new `write_section_toggles`) plus `read_section_toggles`. The `/api/config` GET/POST contract changes shape slightly (adds a `sections` list/dict alongside the existing `fields`) — acceptable since this endpoint has zero external consumers besides this same frontend, built in the immediately-preceding session.

**Tech Stack:** Same as the rest of this project.

**Design decisions:**
- **Opt-out, not opt-in**: missing `*_ENABLED` env var = enabled. Chosen so every already-configured wallet/exchange keeps syncing after this ships, with zero action required from the user — only unchecking something in the new UI disables it.
- **One toggle per section**, matching the Konfiguration page's existing 9 sections exactly (`app/env_file.py`'s `CONFIG_FIELDS` section names) — not per individual wallet/address, matching the user's literal request ("pro Schnittstelle eine Checkbox").
- **Bitcoin's toggle gates BOTH `BITCOIN_WALLETS` and `BITCOIN_XPUBS`** (both live under the "Bitcoin" section); **Cardano's gates both `CARDANO_WALLETS` and `CARDANO_STAKE_WALLETS`**; **the "Ethereum & EVM-Chains" section's toggle is named `EVM_ENABLED`** (not `ETHEREUM_ENABLED`, to match `EVM_CHAINS`/`EvmAdapter` naming already used elsewhere in this codebase) and gates the `ETHEREUM_WALLETS` loop.
- **Exchange toggles combine with the existing key/secret-presence check** (`config.KRAKEN_ENABLED and config.KRAKEN_API_KEY and config.KRAKEN_API_SECRET`), so disabling a section and leaving stale/partial credentials both correctly skip that adapter.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    env_file.py          # MODIFIED — extract _write_raw_updates, add SECTION_TOGGLE_ENV_VAR, read/write_section_toggles
    config.py                 # MODIFIED — _parse_enabled(), 9 new *_ENABLED constants
    adapters/factory.py            # MODIFIED — gate each section behind its *_ENABLED flag
    schemas.py                          # MODIFIED — ConfigUpdateRequest (values + sections)
    main.py                                  # MODIFIED — /api/config GET/POST use the new shape
  tests/
    test_env_file.py                             # MODIFIED
    test_config.py                                    # MODIFIED
    test_factory.py                                        # MODIFIED
    test_api.py                                                # MODIFIED

KryptoWalletDashboard/frontend/src/
  api/
    types.ts              # MODIFIED — ConfigSection, updated ConfigResponse
    client.ts                  # MODIFIED — saveConfig takes (values, sections)
    client.test.ts                  # MODIFIED
  pages/
    Konfiguration.tsx        # MODIFIED — checkbox per section
    Konfiguration.test.tsx        # MODIFIED
```

---

### Task 1: Backend core — section-toggle storage, config loading, factory gating

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/env_file.py`
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_env_file.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_env_file.py`:
```python
from app.env_file import (
    SECTION_TOGGLE_ENV_VAR,
    read_section_toggles,
    write_section_toggles,
)


def test_section_toggle_env_var_covers_every_config_fields_section():
    assert set(SECTION_TOGGLE_ENV_VAR) == {f.section for f in CONFIG_FIELDS}


def test_read_section_toggles_defaults_to_enabled_when_unset(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    toggles = read_section_toggles(str(env_file))

    assert all(toggles.values())
    assert set(toggles) == set(SECTION_TOGGLE_ENV_VAR)


def test_read_section_toggles_reflects_explicit_false(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "CARDANO_ENABLED=false\n")

    toggles = read_section_toggles(str(env_file))

    assert toggles["Cardano"] is False
    assert toggles["Bitcoin"] is True


def test_read_section_toggles_is_case_insensitive(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "CARDANO_ENABLED=False\n")

    toggles = read_section_toggles(str(env_file))

    assert toggles["Cardano"] is False


def test_write_section_toggles_writes_false_and_true(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    write_section_toggles({"Bitcoin": False, "Solana": True}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "BITCOIN_ENABLED=false" in content
    assert "SOLANA_ENABLED=true" in content
    assert "SOLANA_ADDRESSES=main:abc" in content


def test_write_section_toggles_rejects_unknown_section(tmp_path):
    env_file = tmp_path / ".env"

    with pytest.raises(InvalidConfigValueError):
        write_section_toggles({"NotASection": True}, str(env_file))


def test_write_section_toggles_does_nothing_for_empty_updates(tmp_path):
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=main:abc\n")

    write_section_toggles({}, str(env_file))

    assert env_file.read_text(encoding="utf-8") == "SOLANA_ADDRESSES=main:abc\n"


def test_write_config_values_and_write_section_toggles_can_both_touch_the_same_file(tmp_path):
    # Regression test for the _write_raw_updates refactor: both write
    # paths must correctly preserve each other's lines when called in
    # sequence against the same file (this is exactly what
    # api_post_config does: write_config_values then write_section_toggles).
    env_file = tmp_path / ".env"
    _write(env_file, "SOLANA_ADDRESSES=old\n")

    write_config_values({"SOLANA_ADDRESSES": "new"}, str(env_file))
    write_section_toggles({"Bitcoin": False}, str(env_file))

    content = env_file.read_text(encoding="utf-8")
    assert "SOLANA_ADDRESSES=new" in content
    assert "BITCOIN_ENABLED=false" in content
```

Add the required imports at the top of the test file (alongside the existing ones):
```python
import pytest

from app.env_file import CONFIG_FIELDS, InvalidConfigValueError, write_config_values
```
(merge with whatever's already imported there rather than duplicating — read the current file first.)

Append to `KryptoWalletDashboard/backend/tests/test_config.py`:
```python
def test_section_enabled_flags_default_to_true_when_unset(monkeypatch):
    from app import config

    for name in [
        "BITCOIN_ENABLED", "SOLANA_ENABLED", "CARDANO_ENABLED", "VECHAIN_ENABLED",
        "EVM_ENABLED", "KRAKEN_ENABLED", "COINBASE_ENABLED", "MEXC_ENABLED", "BINANCE_ENABLED",
    ]:
        monkeypatch.delenv(name, raising=False)
    config._load_all_from_env()

    assert config.BITCOIN_ENABLED is True
    assert config.SOLANA_ENABLED is True
    assert config.CARDANO_ENABLED is True
    assert config.VECHAIN_ENABLED is True
    assert config.EVM_ENABLED is True
    assert config.KRAKEN_ENABLED is True
    assert config.COINBASE_ENABLED is True
    assert config.MEXC_ENABLED is True
    assert config.BINANCE_ENABLED is True


def test_section_enabled_flag_is_false_when_env_var_is_false(monkeypatch):
    from app import config

    monkeypatch.setenv("CARDANO_ENABLED", "false")
    config._load_all_from_env()

    assert config.CARDANO_ENABLED is False


def test_parse_enabled_treats_missing_as_true():
    from app.config import _parse_enabled

    assert _parse_enabled(None) is True


def test_parse_enabled_is_case_insensitive_for_false():
    from app.config import _parse_enabled

    assert _parse_enabled("False") is False
    assert _parse_enabled("FALSE") is False
    assert _parse_enabled("false") is False


def test_parse_enabled_treats_anything_else_as_true():
    from app.config import _parse_enabled

    assert _parse_enabled("true") is True
    assert _parse_enabled("yes") is True
    assert _parse_enabled("") is True
```

**Important:** the two new `test_config.py` tests that call `config._load_all_from_env()` directly mutate module-global state (same class of issue found and fixed in the previous phase's Task 2 review). Wrap them with explicit `try/finally` snapshotting and restoring every `config.*_ENABLED` attribute they touch, mirroring the pattern already used by `test_reload_config_picks_up_changed_values_from_the_env_file` in this same file — read that existing test first and copy its exact snapshot/restore style. Do NOT rely on bare `monkeypatch.setenv`/`delenv` alone to protect `config._load_all_from_env()`'s reassigned globals, since — as established in the prior phase — that only protects `os.environ`, not the module attributes reassigned by the function itself.

Append to `KryptoWalletDashboard/backend/tests/test_factory.py` (add near the existing Kraken/Coinbase-adapter tests, following their style):
```python
def test_bitcoin_adapter_not_added_when_bitcoin_disabled(monkeypatch):
    from app.adapters.bitcoin import BitcoinAdapter

    monkeypatch.setattr(config, "BITCOIN_ENABLED", False)
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [config.WalletConfig(label="main", address="bc1q...")])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BitcoinAdapter) for a in adapters)


def test_bitcoin_xpub_adapter_also_gated_by_bitcoin_enabled(monkeypatch):
    from app.adapters.bitcoin_xpub import BitcoinXpubAdapter

    monkeypatch.setattr(config, "BITCOIN_ENABLED", False)
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [config.WalletConfig(label="ledger", address="zpub...")])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BitcoinXpubAdapter) for a in adapters)


def test_kraken_adapter_not_added_when_kraken_disabled_even_with_valid_credentials(monkeypatch):
    from app.adapters.kraken import KrakenAdapter

    monkeypatch.setattr(config, "KRAKEN_ENABLED", False)
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "key")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "secret")
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, KrakenAdapter) for a in adapters)


def test_evm_adapters_not_added_when_evm_disabled(monkeypatch):
    monkeypatch.setattr(config, "EVM_ENABLED", False)
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(
        config, "ETHEREUM_WALLETS", [config.WalletConfig(label="main", address="0xabc")]
    )
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "key")
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, EvmAdapter) for a in adapters)


def test_all_sections_enabled_by_default_when_not_monkeypatched(monkeypatch):
    # Every OTHER existing test in this file never monkeypatches the new
    # *_ENABLED flags at all -- this proves that omission is safe (the
    # real, unpatched attribute value is True in this test environment,
    # matching the opt-out-disable design), so none of those tests needed
    # updating for this feature.
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [config.WalletConfig(label="main", address="bc1q...")])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")

    from app.adapters.bitcoin import BitcoinAdapter

    adapters = build_adapters_from_config()

    assert any(isinstance(a, BitcoinAdapter) for a in adapters)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_env_file.py tests/test_config.py tests/test_factory.py -v`
Expected: the new tests FAIL (`ImportError`/`AttributeError` for `SECTION_TOGGLE_ENV_VAR`, `read_section_toggles`, `config.BITCOIN_ENABLED`, etc.); all pre-existing tests in these three files still PASS.

- [ ] **Step 3: Implement `app/env_file.py`**

Read the current file first. Replace `write_config_values`'s body with a version that delegates its actual line-rewriting to a new shared private helper, and add the section-toggle pieces:

```python
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
    literal newline or carriage return."""


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
```

Then update `write_config_values` to use the shared helper instead of duplicating the line-rewriting logic:
```python
def write_config_values(updates: dict[str, str], path: str | None = None) -> None:
    """Apply `updates` (field name -> new value) to the .env file in
    place, preserving every other line (comments, unrelated variables)
    untouched.

    A SECRET field's empty string means "leave the existing stored value
    unchanged" (the UI never shows secrets, so an empty submission isn't
    a deliberate clear). Every other field's empty string is a deliberate
    clear -- the UI does show the current value, so the user seeing and
    blanking it is intentional.

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
```

`InvalidConfigValueError` must be defined ONCE (move its existing definition, if it's currently inline/elsewhere in the file, to sit near the top alongside `SECTION_TOGGLE_ENV_VAR` as shown above — check where it currently lives before moving it, and update nothing else about it).

- [ ] **Step 4: Implement `app/config.py` additions**

Read the current file. Add near the other small parse helpers (after `normalize_pem_env_value`):
```python
def _parse_enabled(env_value: str | None) -> bool:
    """Missing/unset means enabled (opt-out semantics): an existing
    user's already-configured section keeps syncing after this feature
    ships with zero action needed -- only an explicit "false" disables
    it. Anything other than exactly "false" (case-insensitive) is
    treated as enabled, matching how a checkbox naturally maps to
    true/false rather than a stricter boolean grammar."""
    if env_value is None:
        return True
    return env_value.strip().lower() != "false"
```

In `_load_all_from_env()`, add to the `global` declarations and the assignments:
```python
    global BITCOIN_ENABLED, SOLANA_ENABLED, CARDANO_ENABLED, VECHAIN_ENABLED, EVM_ENABLED
    global KRAKEN_ENABLED, COINBASE_ENABLED, MEXC_ENABLED, BINANCE_ENABLED
```
(add these two lines alongside the function's existing `global` lines), and:
```python
    BITCOIN_ENABLED = _parse_enabled(os.getenv("BITCOIN_ENABLED"))
    SOLANA_ENABLED = _parse_enabled(os.getenv("SOLANA_ENABLED"))
    CARDANO_ENABLED = _parse_enabled(os.getenv("CARDANO_ENABLED"))
    VECHAIN_ENABLED = _parse_enabled(os.getenv("VECHAIN_ENABLED"))
    EVM_ENABLED = _parse_enabled(os.getenv("EVM_ENABLED"))
    KRAKEN_ENABLED = _parse_enabled(os.getenv("KRAKEN_ENABLED"))
    COINBASE_ENABLED = _parse_enabled(os.getenv("COINBASE_ENABLED"))
    MEXC_ENABLED = _parse_enabled(os.getenv("MEXC_ENABLED"))
    BINANCE_ENABLED = _parse_enabled(os.getenv("BINANCE_ENABLED"))
```
(add these assignments alongside the function's existing ones, anywhere inside the function body).

- [ ] **Step 5: Implement `app/adapters/factory.py` gating**

Replace the function body with:
```python
def build_adapters_from_config() -> list[TransactionAdapter]:
    adapters: list[TransactionAdapter] = []
    if config.BITCOIN_ENABLED:
        for wallet in config.BITCOIN_WALLETS:
            adapters.append(BitcoinAdapter(account_label=wallet.label, address=wallet.address))
        for wallet in config.BITCOIN_XPUBS:
            adapters.append(BitcoinXpubAdapter(account_label=wallet.label, extended_key=wallet.address))
    if config.SOLANA_ENABLED:
        for wallet in config.SOLANA_WALLETS:
            adapters.append(SolanaAdapter(account_label=wallet.label, address=wallet.address))
    if config.CARDANO_ENABLED:
        for wallet in config.CARDANO_WALLETS:
            adapters.append(CardanoAdapter(account_label=wallet.label, address=wallet.address))
        for wallet in config.CARDANO_STAKE_WALLETS:
            adapters.append(CardanoStakeAdapter(account_label=wallet.label, stake_address=wallet.address))
    if config.VECHAIN_ENABLED:
        for wallet in config.VECHAIN_WALLETS:
            adapters.append(VeChainAdapter(account_label=wallet.label, address=wallet.address))
    if config.EVM_ENABLED:
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
    if config.KRAKEN_ENABLED and config.KRAKEN_API_KEY and config.KRAKEN_API_SECRET:
        adapters.append(
            KrakenAdapter(
                account_label="kraken-main",
                api_key=config.KRAKEN_API_KEY,
                api_secret=config.KRAKEN_API_SECRET,
            )
        )
    if config.COINBASE_ENABLED and config.COINBASE_API_KEY_NAME and config.COINBASE_API_PRIVATE_KEY:
        adapters.append(
            CoinbaseAdapter(
                account_label="coinbase-main",
                api_key_name=config.COINBASE_API_KEY_NAME,
                private_key_pem=config.COINBASE_API_PRIVATE_KEY,
            )
        )
    if config.MEXC_ENABLED and config.MEXC_API_KEY and config.MEXC_API_SECRET:
        adapters.append(
            MexcAdapter(
                account_label="mexc-main",
                api_key=config.MEXC_API_KEY,
                api_secret=config.MEXC_API_SECRET,
                trading_pairs=config.MEXC_TRADING_PAIRS,
            )
        )
    if config.BINANCE_ENABLED and config.BINANCE_API_KEY and config.BINANCE_API_SECRET:
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_env_file.py tests/test_config.py tests/test_factory.py -v`
Expected: PASS, all tests including every new one.

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, 343 baseline + however many new tests, 0 regressions. Pay special attention to whether ANY pre-existing `test_factory.py` test needed changes — per this task's design, none should have, since the new flags default to enabled and those tests never monkeypatch them.

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/env_file.py KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/tests/test_env_file.py KryptoWalletDashboard/backend/tests/test_config.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: add per-section enable/disable toggles, opt-out by default"
```

---

### Task 2: API wiring — `/api/config` GET/POST use the new shape

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/schemas.py`
- Modify: `KryptoWalletDashboard/backend/app/main.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_api.py`:
```python
def test_config_get_endpoint_includes_section_toggles(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CARDANO_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.get("/api/config")

    assert response.status_code == 200
    sections = {s["name"]: s["enabled"] for s in response.json()["sections"]}
    assert sections["Cardano"] is False
    assert sections["Bitcoin"] is True
    app.dependency_overrides.clear()


def test_config_post_endpoint_writes_section_toggles_and_reloads(db_session, tmp_path, monkeypatch):
    from app import config

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))
    monkeypatch.setattr(config, "BITCOIN_ENABLED", config.BITCOIN_ENABLED)

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {}, "sections": {"Bitcoin": False}})

    assert response.status_code == 200
    assert "BITCOIN_ENABLED=false" in env_file.read_text(encoding="utf-8")
    assert config.BITCOIN_ENABLED is False
    app.dependency_overrides.clear()


def test_config_post_endpoint_still_accepts_values_alongside_sections(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOLANA_ADDRESSES=old\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post(
        "/api/config",
        json={"values": {"SOLANA_ADDRESSES": "new"}, "sections": {}},
    )

    assert response.status_code == 200
    assert "SOLANA_ADDRESSES=new" in env_file.read_text(encoding="utf-8")
    app.dependency_overrides.clear()


def test_config_post_endpoint_rejects_unknown_section(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {}, "sections": {"NotASection": True}})

    assert response.status_code == 400
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_api.py -v`
Expected: FAIL — `/api/config` doesn't accept/return the new shape yet (422s for the POST tests since the body no longer matches a bare `dict[str,str]`; KeyError/assertion failures for the GET test since there's no `sections` key yet).

- [ ] **Step 3: Add `ConfigUpdateRequest` to `app/schemas.py`**

Add near `AccountRef`/`DeleteAccountsRequest`:
```python
class ConfigUpdateRequest(BaseModel):
    values: dict[str, str] = {}
    sections: dict[str, bool] = {}
```

- [ ] **Step 4: Update `app/main.py`**

Update the import line:
```python
from app.env_file import (
    CONFIG_FIELDS,
    SECTION_TOGGLE_ENV_VAR,
    InvalidConfigValueError,
    read_config_values,
    read_section_toggles,
    write_config_values,
    write_section_toggles,
)
```
```python
from app.schemas import ConfigUpdateRequest, DeleteAccountsRequest, PortfolioEntryOut, TransactionOut
```

Replace the two `/api/config` routes:
```python
@app.get("/api/config")
def api_get_config():
    values = read_config_values()
    toggles = read_section_toggles()
    return {
        "sections": [
            {"name": name, "enabled": toggles[name]} for name in SECTION_TOGGLE_ENV_VAR
        ],
        "fields": [
            {
                "name": field.name,
                "section": field.section,
                "label": field.label,
                "is_secret": field.is_secret,
                "hint": field.hint,
                "value": values[field.name],
            }
            for field in CONFIG_FIELDS
        ],
    }


@app.post("/api/config")
def api_post_config(payload: ConfigUpdateRequest):
    try:
        write_config_values(payload.values)
        write_section_toggles(payload.sections)
    except InvalidConfigValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    reload_config()
    return {"status": "ok"}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_api.py -v`
Expected: PASS, all tests including the 4 new ones. Note the OLD `POST /api/config` tests from the prior phase (e.g. `test_config_post_endpoint_writes_file_and_reloads`) sent a bare `{"SOLANA_ADDRESSES": "..."}` body — these will now FAIL validation (422) since the body shape changed to `{"values": {...}, "sections": {...}}`. **Find and update every pre-existing test in `test_api.py` that POSTs to `/api/config`** to wrap its payload as `{"values": {...}}` (omit `sections` — it defaults to `{}`). Do the same for any pre-existing test asserting on `GET /api/config`'s response shape that indexes `response.json()["fields"]` directly at the top level — that's unaffected (still there, unchanged), but double check none of them do something like `assert response.json() == {"fields": [...]}` (an exact equality that would now fail because of the added `sections` key) rather than checking `response.json()["fields"]` specifically.

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, 0 regressions once the pre-existing `/api/config` tests are updated to the new body shape.

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/backend/app/schemas.py KryptoWalletDashboard/backend/app/main.py KryptoWalletDashboard/backend/tests/test_api.py
git commit -m "feat: expose per-section toggles through /api/config"
```

---

### Task 3: Frontend — checkbox per section on the Konfiguration page

**Files:**
- Modify: `KryptoWalletDashboard/frontend/src/api/types.ts`
- Modify: `KryptoWalletDashboard/frontend/src/api/client.ts`
- Modify: `KryptoWalletDashboard/frontend/src/api/client.test.ts`
- Modify: `KryptoWalletDashboard/frontend/src/pages/Konfiguration.tsx`
- Modify: `KryptoWalletDashboard/frontend/src/pages/Konfiguration.test.tsx`

- [ ] **Step 1: Write the failing tests**

In `client.test.ts`, find the existing `describe("fetchConfig", ...)` and `describe("saveConfig", ...)` blocks (from the prior phase) and update/extend them:
```typescript
describe("fetchConfig", () => {
  it("returns the parsed sections and fields", async () => {
    mockFetchOnce({
      sections: [{ name: "Bitcoin", enabled: true }],
      fields: [
        { name: "SOLANA_ADDRESSES", section: "Solana", label: "Adressen", is_secret: false, hint: "", value: "main:abc" },
      ],
    });

    const result = await fetchConfig();

    expect(result.sections[0].name).toBe("Bitcoin");
    expect(result.fields[0].name).toBe("SOLANA_ADDRESSES");
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(fetchConfig()).rejects.toThrow();
  });
});

describe("saveConfig", () => {
  it("POSTs values and sections together as JSON", async () => {
    mockFetchOnce({ status: "ok" });

    await saveConfig({ SOLANA_ADDRESSES: "main:new" }, { Bitcoin: false });

    const [url, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/config");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      values: { SOLANA_ADDRESSES: "main:new" },
      sections: { Bitcoin: false },
    });
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce(null, false, 500);

    await expect(saveConfig({}, {})).rejects.toThrow();
  });
});
```
(Read the current file first — these blocks already exist from the prior phase; replace their bodies with the above rather than duplicating a second `describe` block with the same name.)

In `Konfiguration.test.tsx`, read the current file first (it already exists from the prior phase with a `FIELDS` fixture and several tests). Update the mocked `fetchConfig` return value in EVERY existing test to include a `sections` array (e.g. `sections: [{ name: "Solana", enabled: true }, { name: "Kraken", enabled: true }]`, matching whatever sections that test's `FIELDS` fixture actually uses), since the component will now expect that key to exist. Then add these new tests:
```typescript
it("renders a checkbox per section reflecting its enabled state", async () => {
  vi.spyOn(client, "fetchConfig").mockResolvedValue({
    sections: [
      { name: "Solana", enabled: true },
      { name: "Kraken", enabled: false },
    ],
    fields: FIELDS,
  });

  render(<Konfiguration />);

  const solanaCheckbox = (await screen.findByRole("checkbox", { name: /Solana/ })) as HTMLInputElement;
  const krakenCheckbox = screen.getByRole("checkbox", { name: /Kraken/ }) as HTMLInputElement;
  expect(solanaCheckbox.checked).toBe(true);
  expect(krakenCheckbox.checked).toBe(false);
});

it("includes the current section toggle state when saving", async () => {
  vi.spyOn(client, "fetchConfig").mockResolvedValue({
    sections: [{ name: "Solana", enabled: true }],
    fields: FIELDS,
  });
  const saveSpy = vi.spyOn(client, "saveConfig").mockResolvedValue(undefined);

  render(<Konfiguration />);
  const solanaCheckbox = await screen.findByRole("checkbox", { name: /Solana/ });
  fireEvent.click(solanaCheckbox);
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

  await waitFor(() =>
    expect(saveSpy).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ Solana: false }),
    ),
  );
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/frontend/`): `npm.cmd test -- client.test.ts Konfiguration.test.tsx`
Expected: FAIL — `saveConfig` still takes only one argument, `ConfigResponse` has no `sections`, no checkbox is rendered.

- [ ] **Step 3: Update `api/types.ts`**

Add:
```typescript
export interface ConfigSection {
  name: string;
  enabled: boolean;
}
```
Update `ConfigResponse`:
```typescript
export interface ConfigResponse {
  sections: ConfigSection[];
  fields: ConfigField[];
}
```

- [ ] **Step 4: Update `api/client.ts`**

Add `ConfigSection` to the type-only import from `./types`. Replace `saveConfig`:
```typescript
export async function saveConfig(
  values: Record<string, string>,
  sections: Record<string, boolean>,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values, sections }),
  });
  if (!response.ok) {
    throw new Error(`Konfiguration konnte nicht gespeichert werden: ${await errorDetail(response)}`);
  }
}
```

- [ ] **Step 5: Update `pages/Konfiguration.tsx`**

Read the current file first. Add section-toggle state and wire a checkbox into each section's `<legend>`:
```tsx
import { useEffect, useState } from "react";
import { fetchConfig, saveConfig } from "../api/client";
import type { ConfigField } from "../api/types";

function groupBySection(fields: ConfigField[]): Map<string, ConfigField[]> {
  const groups = new Map<string, ConfigField[]>();
  for (const field of fields) {
    const existing = groups.get(field.section) ?? [];
    existing.push(field);
    groups.set(field.section, existing);
  }
  return groups;
}

function Konfiguration() {
  const [fields, setFields] = useState<ConfigField[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [sections, setSections] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchConfig()
      .then((response) => {
        setFields(response.fields);
        const initialValues: Record<string, string> = {};
        for (const field of response.fields) {
          initialValues[field.name] = field.value;
        }
        setValues(initialValues);

        const initialSections: Record<string, boolean> = {};
        for (const section of response.sections) {
          initialSections[section.name] = section.enabled;
        }
        setSections(initialSections);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await saveConfig(values, sections);
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (error && fields === null) {
    return (
      <div className="text-red-600">
        {error}. Läuft das Backend unter http://127.0.0.1:8000?
      </div>
    );
  }

  if (fields === null) {
    return <div>Konfiguration wird geladen…</div>;
  }

  const groupedSections = groupBySection(fields);

  return (
    <div>
      <h2 className="mb-4 text-xl font-semibold">Konfiguration</h2>
      <p className="mb-6 text-sm text-gray-500">
        Änderungen werden sofort in der .env-Datei gespeichert und beim nächsten Sync verwendet - kein
        Neustart nötig. Secret-Felder zeigen nie den gespeicherten Wert - leer lassen, um ihn unverändert
        zu behalten. Eine abgewählte Schnittstelle wird beim Sync übersprungen, ihre Werte bleiben aber
        erhalten.
      </p>

      {Array.from(groupedSections.entries()).map(([section, sectionFields]) => (
        <fieldset key={section} className="mb-6 rounded border border-gray-200 p-4">
          <legend className="flex items-center gap-2 px-1 text-sm font-semibold">
            <input
              type="checkbox"
              role="checkbox"
              aria-label={section}
              checked={sections[section] ?? true}
              onChange={(e) =>
                setSections((prev) => ({ ...prev, [section]: e.target.checked }))
              }
            />
            {section}
          </legend>
          <div className={sections[section] === false ? "space-y-3 opacity-50" : "space-y-3"}>
            {sectionFields.map((field) => (
              <div key={field.name}>
                <label htmlFor={field.name} className="mb-1 block text-sm text-gray-700">
                  {field.label}
                </label>
                <input
                  id={field.name}
                  type={field.is_secret ? "password" : "text"}
                  autoComplete={field.is_secret ? "new-password" : "off"}
                  value={values[field.name] ?? ""}
                  placeholder={field.is_secret ? "•••• (unverändert lassen, um bestehenden Wert zu behalten)" : field.hint}
                  onChange={(e) => setValues((prev) => ({ ...prev, [field.name]: e.target.value }))}
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
                />
                {!field.is_secret && field.hint && (
                  <p className="mt-1 text-xs text-gray-400">{field.hint}</p>
                )}
              </div>
            ))}
          </div>
        </fieldset>
      ))}

      <button
        onClick={handleSave}
        disabled={saving}
        className="rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
      >
        {saving ? "Speichert…" : "Speichern"}
      </button>

      {saved && <p className="mt-4 text-green-700">Gespeichert.</p>}
      {error && fields !== null && <p className="mt-4 text-red-600">{error}</p>}
    </div>
  );
}

export default Konfiguration;
```

Note the `opacity-50` on a disabled section's fields is a purely visual cue (fields stay editable even when the section is unchecked, since the plan's design is "keep the values, just skip the sync" — not "lock the inputs"). This is a deliberate, minor UX choice consistent with the feature's goal; no test asserts on it specifically.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npm.cmd test -- client.test.ts Konfiguration.test.tsx`
Expected: PASS, all tests.

Run the full frontend suite: `npm.cmd test`
Expected: PASS, 0 regressions.

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/frontend/src/api/types.ts KryptoWalletDashboard/frontend/src/api/client.ts KryptoWalletDashboard/frontend/src/api/client.test.ts KryptoWalletDashboard/frontend/src/pages/Konfiguration.tsx KryptoWalletDashboard/frontend/src/pages/Konfiguration.test.tsx
git commit -m "feat: add per-section enable/disable checkboxes to the Konfiguration page"
```

---

### Task 4: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document the toggle behavior**

In the existing "## Konfiguration über die Web-UI" section, add:
```markdown
Jede Sektion (Bitcoin, Solana, Cardano, VeChain, Ethereum & EVM-Chains,
Kraken, Coinbase, MEXC, Binance) hat zusätzlich eine Checkbox. Ist sie
abgewählt, werden die zugehörigen Adressen/Keys beim nächsten Sync
**nicht** verwendet - sie bleiben aber unverändert in der `.env`
gespeichert, sodass man eine Sektion jederzeit wieder aktivieren kann,
ohne die Werte neu eintragen zu müssen. Fehlt der entsprechende
`*_ENABLED`-Eintrag in der `.env` ganz (z.B. bei allen bisherigen
Installationen vor diesem Feature), gilt die Sektion als aktiviert -
bestehende Konfigurationen syncen also unverändert weiter, ohne dass
etwas nachgetragen werden muss.
```

- [ ] **Step 2: Commit**

```bash
git add KryptoWalletDashboard/backend/README.md
git commit -m "docs: document per-section enable/disable toggles"
```

---

## Self-Review Notes

- **Spec coverage:** one checkbox per section (Task 3), gates that section's sync (Task 1's factory.py changes), avoids sync errors for unconfigured/unwanted sections while preserving the underlying values (opt-out default + values never cleared by toggling, Task 1 + design decisions). All match the user's request.
- **Placeholder scan:** no TBD/TODO; every step has complete code.
- **Type/signature consistency:** `read_section_toggles(path=None)`/`write_section_toggles(updates, path=None)` signatures match between Task 1's implementation, its tests, and Task 2's `main.py` usage. `saveConfig(values, sections)`'s two-argument signature matches between Task 3's `client.ts` implementation, its tests, and `Konfiguration.tsx`'s call site. `ConfigUpdateRequest{values, sections}` matches exactly what `Konfiguration.tsx`'s `saveConfig` call produces as a JSON body and what Task 2's `api_post_config` expects.
- **Backward compatibility deliberately verified as a first-class concern**: Task 1's Step 6 explicitly calls out checking that no pre-existing `test_factory.py` test needed changes (proving the opt-out-by-default design actually holds in practice, not just in intent) — this mirrors the exact kind of "verify a stated design guarantee against the real, current test suite" discipline that caught real regressions in the immediately-preceding phase.
