# Phase 4a – Bitcoin-xpub-Scanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `BitcoinXpubAdapter` that, given an xpub/ypub/zpub (HD wallet extended public key), automatically derives and scans all addresses that have ever been used (BIP44/49/84 gap-limit scanning) and reports the wallet's true net BTC movement per transaction — so a user no longer has to manually find and enter every individual address a wallet like Ledger/Trezor generated over time.

**Architecture:** Blockstream's Esplora API (already used by the existing `BitcoinAdapter`) has no xpub endpoint, so addresses are derived client-side (via the new `bitcoinlib` dependency) and queried one by one through the existing per-address endpoints. The existing single-address transaction-normalization logic in `app/adapters/bitcoin.py` is generalized (from "does this vin/vout belong to *one* address" to "does this vin/vout belong to *any address in this owned set*") and extracted into a shared function, so both the old single-address path and the new multi-address xpub path use identical, already-tested logic — critically, this generalization also makes wallet-level accounting *correct* for multi-address wallets: a transaction that moves BTC between two addresses of the *same* xpub (e.g. spend + change) nets to zero and is correctly not reported as a taxable event, instead of incorrectly appearing as one address's outflow plus another's inflow.

**Tech Stack:** Same as Phase 1 (Python, `requests`, `responses` for test mocking, pytest), plus a new dependency: `bitcoinlib` (BIP32 key derivation and address encoding for all three Bitcoin address formats).

**Related docs:**
- [`docs/superpowers/specs/2026-08-06-phase4a-btc-xpub-design.md`](../specs/2026-08-06-phase4a-btc-xpub-design.md)

**Scope notes (decided during design, confirmed with user):**
- **Gap limit is fixed at 20**, not configurable — the universal industry-standard default used by essentially every wallet, not a per-user setting worth exposing.
- **No caching of discovered addresses between syncs.** Every sync re-derives and re-scans from address index 0 on both chains (receive `m/0/i` and change `m/1/i`). This is a deliberate simplicity choice (no new persistent state), mirroring the already-accepted "refetch everything, rely on `sync.py`'s `external_id` dedup" pattern from the Binance adapter's trade-fetching. More API calls per sync; correct and simple.
- **Both `BITCOIN_ADDRESSES` (existing, single fixed addresses) and `BITCOIN_XPUBS` (new, HD wallets) work independently and simultaneously** — this is additive, not a replacement.
- **`bitcoinlib`'s exact call signature for parsing xpub/ypub/zpub and producing the right address format was not fully confirmed during design-time research** (documentation was ambiguous on whether witness type is auto-detected from the key prefix or must be passed explicitly). Task 2 below includes an explicit verification step for this — treat the plan's code as the intended *shape*, not a guaranteed-correct final API call; if the installed `bitcoinlib` version behaves differently, adapt the call while keeping the function's documented contract (input: extended key string + chain + index: output: correctly-formatted address string for that key's type) intact. This is the same "verify external API/library shape against what's actually installed, treat intent as authoritative" caveat already used successfully in prior phases (e.g. MEXC/Binance API research).
- **Wallet-level netting for multi-address transactions is a deliberate correctness improvement**, not just refactoring for its own sake — see the Architecture note above. Get this right; it's the main way this feature could silently produce wrong numbers for a tax tool.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      bitcoin.py            # MODIFIED — extract fetch_all_pages_for_address() and
                             #            normalize_bitcoin_tx() to module level,
                             #            generalized to a set of owned addresses;
                             #            BitcoinAdapter becomes a thin wrapper
      bitcoin_hd.py          # NEW — derive_address(): BIP32 derivation + address encoding
      bitcoin_xpub.py         # NEW — BitcoinXpubAdapter: gap-limit discovery + fetch + normalize
      factory.py                # MODIFIED — build BitcoinXpubAdapter per BITCOIN_XPUBS entry
    config.py                    # MODIFIED — BITCOIN_XPUBS (reuses existing parse_wallets())
  requirements.txt                  # MODIFIED — add bitcoinlib
  .env.example                        # MODIFIED — document BITCOIN_XPUBS
  README.md                            # MODIFIED — document xpub scanning
  tests/
    test_bitcoin_adapter.py                # MODIFIED — verify unchanged behavior after refactor
    test_bitcoin_hd.py                        # NEW — derive_address() tests
    test_bitcoin_xpub_adapter.py                # NEW — BitcoinXpubAdapter tests
    test_config.py                                # MODIFIED — BITCOIN_XPUBS parsing
    test_factory.py                                  # MODIFIED — factory wiring
```

---

### Task 1: Extract & Generalize Shared Bitcoin Normalization Logic

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/bitcoin.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_bitcoin_adapter.py` (only if needed — see Step 1)

**Why this comes first:** Task 4's `BitcoinXpubAdapter` needs to reuse the exact same vin/vout-netting and pagination logic that `BitcoinAdapter` already has, tested and working. Rather than duplicating it, this task extracts it to module-level functions generalized to accept a *set* of owned addresses instead of one fixed address — `BitcoinAdapter` then becomes a 1-line-different caller (`{self.address}` instead of a multi-address set), and behavior for the existing single-address case is unchanged.

- [ ] **Step 1: Read the existing test file to confirm nothing hardcodes internals that would break**

Read `KryptoWalletDashboard/backend/tests/test_bitcoin_adapter.py` in full. Confirm (as of this plan's writing) it does NOT reference `BitcoinAdapter.API_BASE` as a class attribute anywhere — it hardcodes the URL string `"https://blockstream.info/api/..."` directly in each test. This means moving `API_BASE` to a module-level constant is safe and requires no test changes. If, by the time you run this, the test file has been changed and now *does* reference `BitcoinAdapter.API_BASE`, keep it working too (e.g. `class BitcoinAdapter: API_BASE = API_BASE` — assign the class attribute from the module constant at class-definition time, so both remain valid and can never drift apart).

- [ ] **Step 2: Run the existing tests to confirm the starting baseline is green**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_bitcoin_adapter.py -v`
Expected: PASS (5 tests, all pre-existing).

- [ ] **Step 3: Refactor `app/adapters/bitcoin.py`**

Replace the entire contents of `KryptoWalletDashboard/backend/app/adapters/bitcoin.py` with:
```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

SATS_PER_BTC = Decimal(10**8)
API_BASE = "https://blockstream.info/api"


def fetch_all_pages_for_address(address: str) -> list[dict]:
    """Walk Blockstream's paginated txs endpoint for a single address.

    The base endpoint returns mempool txs plus only the most recent 25
    confirmed txs. Older confirmed txs must be fetched page-by-page via
    the /txs/chain/:last_seen_txid endpoint, keyed off the last
    confirmed txid seen so far, until a page comes back with fewer than
    25 confirmed txs (or none at all).
    """
    response = requests.get(f"{API_BASE}/address/{address}/txs", timeout=10)
    response.raise_for_status()
    page = response.json()

    all_txs: list[dict] = []
    while True:
        all_txs.extend(page)
        confirmed = [t for t in page if t.get("status", {}).get("confirmed")]
        if len(confirmed) < 25:
            break
        last_txid = confirmed[-1]["txid"]
        response = requests.get(
            f"{API_BASE}/address/{address}/txs/chain/{last_txid}", timeout=10
        )
        response.raise_for_status()
        page = response.json()

    return all_txs


def normalize_bitcoin_tx(
    tx: dict,
    owned_addresses: set[str],
    account_label: str,
    since: datetime | None,
) -> NormalizedTransaction | None:
    """Compute a single Bitcoin address (or HD wallet's) net BTC change for
    one transaction, and normalize it -- or return None if the tx should be
    skipped (unconfirmed, older than `since`, or nets to zero change for the
    owned addresses, e.g. a pure spend+change-back within the same wallet).

    `owned_addresses` is a set rather than a single address so this same
    function serves both the single-address BitcoinAdapter (a 1-element
    set) and the multi-address BitcoinXpubAdapter (every address discovered
    for an HD wallet) -- computing net vin/vout against the *whole* owned
    set, not per-address, is what makes internal wallet transfers (spend
    from one of our addresses, change back to another of our addresses)
    correctly net to zero instead of appearing as two separate taxable
    events.
    """
    block_time = tx.get("status", {}).get("block_time")
    if block_time is None:
        return None
    timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
    if since is not None and timestamp <= since:
        return None

    vin_value = sum(
        vin.get("prevout", {}).get("value", 0)
        for vin in tx["vin"]
        if vin.get("prevout", {}).get("scriptpubkey_address") in owned_addresses
    )
    vout_value = sum(
        vout["value"]
        for vout in tx["vout"]
        if vout.get("scriptpubkey_address") in owned_addresses
    )
    net_sats = vout_value - vin_value
    if net_sats == 0:
        return None

    fee_amount = None
    fee_asset = None
    if net_sats < 0:
        total_vin = sum(vin.get("prevout", {}).get("value", 0) for vin in tx["vin"])
        total_vout = sum(vout["value"] for vout in tx["vout"])
        fee_sats = total_vin - total_vout
        fee_amount = Decimal(fee_sats) / SATS_PER_BTC
        fee_asset = "BTC"

    return NormalizedTransaction(
        timestamp=timestamp,
        source_type="chain",
        source_name="bitcoin",
        account_label=account_label,
        tx_type="transfer_in" if net_sats > 0 else "transfer_out",
        asset="BTC",
        amount=Decimal(abs(net_sats)) / SATS_PER_BTC,
        fee_amount=fee_amount,
        fee_asset=fee_asset,
        external_id=tx["txid"],
        raw_json=json.dumps(tx),
    )


class BitcoinAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for tx in fetch_all_pages_for_address(self.address):
            ntx = normalize_bitcoin_tx(tx, {self.address}, self.account_label, since)
            if ntx is not None:
                results.append(ntx)
        return results
```

- [ ] **Step 4: Run the existing tests to confirm nothing broke**

Run: `.venv/Scripts/pytest tests/test_bitcoin_adapter.py -v`
Expected: PASS (still 5 tests, unchanged, all green — this refactor must be behavior-preserving for the existing single-address case).

Run the full backend suite too: `.venv/Scripts/pytest -v`
Expected: PASS, all 195 tests green, no regressions anywhere else.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/bitcoin.py
git commit -m "refactor: extract and generalize Bitcoin tx normalization to a shared, multi-address-aware function"
```

---

### Task 2: HD Address Derivation Helper

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/bitcoin_hd.py`
- Create: `KryptoWalletDashboard/backend/tests/test_bitcoin_hd.py`
- Modify: `KryptoWalletDashboard/backend/requirements.txt` (add `bitcoinlib`)

**Contract this task must deliver:** a function `derive_address(extended_key: str, chain: int, index: int) -> str` that takes an xpub/ypub/zpub string, a chain (`0` = receive, `1` = change), and a non-hardened address index, and returns the correctly-formatted Bitcoin address (`1...` for xpub, `3...` for ypub, `bc1...` for zpub) at derivation path `{chain}/{index}` relative to the given extended key.

- [ ] **Step 1: Install `bitcoinlib` and verify its actual API before writing tests**

From `KryptoWalletDashboard/backend/`:
```bash
.venv/Scripts/pip install bitcoinlib
```

Add `bitcoinlib` to `KryptoWalletDashboard/backend/requirements.txt` (alongside the existing pinned/unpinned deps, matching whatever style — pinned version or not — the file already uses for other entries).

**Before writing any test or implementation code**, verify `bitcoinlib`'s actual behavior interactively. Run this from `KryptoWalletDashboard/backend/` with `.venv/Scripts/python`:
```python
from bitcoinlib.keys import HDKey

# BIP32 official spec test vector 1 master public key (well-known, public,
# not a real wallet — https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki).
TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"

k = HDKey(import_key=TEST_XPUB)
child = k.subkey_for_path("0/0")  # or k.key_for_path(...) depending on installed version -- try both if one errors
print(child.address())
print(type(child.address()))
```
Confirm: (a) this doesn't raise, (b) `child.address()` returns a string starting with `"1"` (legacy P2PKH — the format implied by the `xpub` prefix). Then check whether the library auto-detects format from the prefix, or needs an explicit `witness_type`/`encoding` argument — try converting the same key material to a `zpub`-style call (e.g. `k.address(script_type='p2wpkh')` or `k.address(encoding='bech32')`, whatever the installed version's actual method signature is — check `help(HDKey.address)` or `help(HDKey)` in the same Python session) and confirm you can produce a `bc1...`-prefixed address on demand. Note exactly what worked in your self-review — this determines whether `derive_address()` below needs to pass an explicit format argument derived from the key's prefix (`xpub`/`ypub`/`zpub`), or whether calling `.address()` with no arguments already does the right thing based on what `HDKey(import_key=...)` parsed.

**If any of the above doesn't work as shown**, that's expected — the design doc flagged this as unverified. Adapt: the *contract* (`derive_address(extended_key, chain, index) -> address string in the format implied by extended_key's prefix`) is what matters, not the literal code below. Use `pip show bitcoinlib` to see what's actually installed and consult its actual installed docstrings (`help(...)`) rather than guessing further.

- [ ] **Step 2: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_bitcoin_hd.py`:
```python
from app.adapters.bitcoin_hd import derive_address

# BIP32 official spec test vector 1 master public key -- well-known, public
# test data from the BIP32 specification itself, not a real wallet.
# https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki
TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"


def test_derives_a_legacy_p2pkh_address_from_an_xpub():
    address = derive_address(TEST_XPUB, chain=0, index=0)

    assert address.startswith("1")


def test_derivation_is_deterministic():
    address_a = derive_address(TEST_XPUB, chain=0, index=0)
    address_b = derive_address(TEST_XPUB, chain=0, index=0)

    assert address_a == address_b


def test_different_indexes_produce_different_addresses():
    address_0 = derive_address(TEST_XPUB, chain=0, index=0)
    address_1 = derive_address(TEST_XPUB, chain=0, index=1)

    assert address_0 != address_1


def test_receive_and_change_chains_produce_different_addresses():
    receive_address = derive_address(TEST_XPUB, chain=0, index=0)
    change_address = derive_address(TEST_XPUB, chain=1, index=0)

    assert receive_address != change_address


def test_ypub_produces_a_p2sh_segwit_address():
    # Convert the same underlying key material to a ypub (BIP49) test
    # fixture using bitcoinlib itself, rather than hand-writing/guessing a
    # ypub string -- see Step 1's interactive verification for how to do
    # this with your installed bitcoinlib version's actual API.
    from bitcoinlib.keys import HDKey

    k = HDKey(import_key=TEST_XPUB)
    ypub = k.public_master(witness_type="p2sh-segwit").wif()  # adjust to match verified API from Step 1

    address = derive_address(ypub, chain=0, index=0)

    assert address.startswith("3")


def test_zpub_produces_a_native_segwit_address():
    from bitcoinlib.keys import HDKey

    k = HDKey(import_key=TEST_XPUB)
    zpub = k.public_master(witness_type="segwit").wif()  # adjust to match verified API from Step 1

    address = derive_address(zpub, chain=0, index=0)

    assert address.startswith("bc1")
```

**Important:** the last two tests (`test_ypub_produces_a_p2sh_segwit_address`, `test_zpub_produces_a_native_segwit_address`) construct their own ypub/zpub test fixtures at test-run time using `bitcoinlib` itself (converting the same BIP32 test-vector key material into each format), rather than this plan hardcoding literal ypub/zpub strings whose correctness couldn't be independently verified during design. Adjust the exact `bitcoinlib` calls (`public_master`, `wif`, `witness_type` values, etc.) to match whatever you verified actually works in Step 1 — the important thing each test checks is unchanged: same key material, different declared format, correctly different address prefix.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_bitcoin_hd.py -v`
Expected: FAIL — `app/adapters/bitcoin_hd.py` doesn't exist yet.

- [ ] **Step 4: Implement `app/adapters/bitcoin_hd.py`**

```python
from bitcoinlib.keys import HDKey


def derive_address(extended_key: str, chain: int, index: int) -> str:
    """Derive the Bitcoin address at path `{chain}/{index}` relative to the
    given extended public key (xpub/ypub/zpub), in the address format
    implied by that key's own prefix (legacy/P2SH-segwit/native-segwit
    respectively). `chain` is 0 for the receive chain, 1 for change."""
    key = HDKey(import_key=extended_key)
    child = key.subkey_for_path(f"{chain}/{index}")
    return child.address()
```

(This is the plan's best-effort implementation based on design-time research — replace the two lines inside the function with whatever you verified actually works in Step 1 if `bitcoinlib`'s real API differs. The function's signature and docstring/contract must stay exactly as shown, since Task 3 and Task 4 depend on it.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_bitcoin_hd.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Manual cross-check (not an automated test — a one-time sanity check for your self-review)**

Using the `TEST_XPUB` above, derive the address at `chain=0, index=0` via your implementation, then independently cross-check that exact address using a well-known, trusted third-party BIP32 address-derivation tool (e.g. search for an "xpub address viewer" / "BIP32 test vector" tool, or ian coleman's BIP39 tool's "BIP32" tab, entering the same `TEST_XPUB` and path `m/0/0`). Confirm they match. **Never enter a real wallet's xpub into a third-party website** — this check uses only the well-known, public BIP32 test vector, never real user data. Note the result of this cross-check in your self-review report.

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/bitcoin_hd.py KryptoWalletDashboard/backend/tests/test_bitcoin_hd.py KryptoWalletDashboard/backend/requirements.txt
git commit -m "feat: derive Bitcoin addresses from xpub/ypub/zpub extended public keys"
```

---

### Task 3: Gap-Limit Address Discovery

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/bitcoin_gap_scan.py`
- Create: `KryptoWalletDashboard/backend/tests/test_bitcoin_gap_scan.py`

**Contract:** `discover_used_addresses(extended_key: str) -> set[str]` — derives addresses on both the receive (`chain=0`) and change (`chain=1`) chains starting at index 0, checking each one via Blockstream's `/address/:address` endpoint for any transaction history (confirmed or mempool), stopping each chain after 20 consecutive addresses with zero history. Returns the union of every address found to have history on either chain.

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_bitcoin_gap_scan.py`:
```python
import responses

from app.adapters.bitcoin_gap_scan import discover_used_addresses
from app.adapters.bitcoin_hd import derive_address

# Same well-known, public BIP32 test vector used in test_bitcoin_hd.py.
TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"

API_BASE = "https://blockstream.info/api"


def _mock_address_stats(address, tx_count, mempool_count=0):
    responses.add(
        responses.GET,
        f"{API_BASE}/address/{address}",
        json={
            "chain_stats": {"tx_count": tx_count},
            "mempool_stats": {"tx_count": mempool_count},
        },
        status=200,
    )


@responses.activate
def test_stops_a_chain_after_20_consecutive_unused_addresses():
    # 3 used addresses on the receive chain, then 20 unused -> scan stops,
    # address index 23 (the 21st unused in a row) is never queried.
    for i in range(3):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=1)
    for i in range(3, 23):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    # Change chain: nothing used at all -> scan stops after 20 unused, index 0.
    for i in range(20):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    expected_used = {derive_address(TEST_XPUB, chain=0, index=i) for i in range(3)}
    assert used == expected_used
    # Confirm address index 23 on the receive chain was never queried --
    # the scan must have stopped exactly at the 20-unused-in-a-row boundary.
    queried_addresses = {call.request.url.rsplit("/", 1)[-1] for call in responses.calls}
    assert derive_address(TEST_XPUB, chain=0, index=23) not in queried_addresses


@responses.activate
def test_mempool_only_activity_counts_as_used():
    _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=0), tx_count=0, mempool_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    for i in range(20):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    assert used == {derive_address(TEST_XPUB, chain=0, index=0)}


@responses.activate
def test_both_chains_are_scanned_independently():
    _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=0), tx_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=0), tx_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    assert used == {
        derive_address(TEST_XPUB, chain=0, index=0),
        derive_address(TEST_XPUB, chain=1, index=0),
    }


@responses.activate
def test_no_usage_at_all_returns_empty_set():
    for chain in (0, 1):
        for i in range(20):
            _mock_address_stats(derive_address(TEST_XPUB, chain=chain, index=i), tx_count=0)

    assert discover_used_addresses(TEST_XPUB) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_bitcoin_gap_scan.py -v`
Expected: FAIL — `app/adapters/bitcoin_gap_scan.py` doesn't exist yet.

- [ ] **Step 3: Implement `app/adapters/bitcoin_gap_scan.py`**

```python
import requests

from app.adapters.bitcoin import API_BASE
from app.adapters.bitcoin_hd import derive_address

GAP_LIMIT = 20


def _address_is_used(address: str) -> bool:
    response = requests.get(f"{API_BASE}/address/{address}", timeout=10)
    response.raise_for_status()
    data = response.json()
    chain_count = data.get("chain_stats", {}).get("tx_count", 0)
    mempool_count = data.get("mempool_stats", {}).get("tx_count", 0)
    return (chain_count + mempool_count) > 0


def _scan_chain(extended_key: str, chain: int) -> set[str]:
    used: set[str] = set()
    unused_streak = 0
    index = 0
    while unused_streak < GAP_LIMIT:
        address = derive_address(extended_key, chain, index)
        if _address_is_used(address):
            used.add(address)
            unused_streak = 0
        else:
            unused_streak += 1
        index += 1
    return used


def discover_used_addresses(extended_key: str) -> set[str]:
    """Scan both the receive (chain 0) and change (chain 1) derivation
    chains of an HD wallet's extended public key for used addresses,
    stopping each chain after GAP_LIMIT consecutive unused addresses --
    the same gap-limit convention essentially every wallet uses."""
    return _scan_chain(extended_key, 0) | _scan_chain(extended_key, 1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_bitcoin_gap_scan.py -v`
Expected: PASS (4 tests).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/bitcoin_gap_scan.py KryptoWalletDashboard/backend/tests/test_bitcoin_gap_scan.py
git commit -m "feat: gap-limit scanning to discover an HD wallet's used Bitcoin addresses"
```

---

### Task 4: `BitcoinXpubAdapter`

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/bitcoin_xpub.py`
- Create: `KryptoWalletDashboard/backend/tests/test_bitcoin_xpub_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_bitcoin_xpub_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.bitcoin_hd import derive_address
from app.adapters.bitcoin_xpub import BitcoinXpubAdapter

TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
API_BASE = "https://blockstream.info/api"

RECEIVE_0 = derive_address(TEST_XPUB, chain=0, index=0)
CHANGE_0 = derive_address(TEST_XPUB, chain=1, index=0)


def _tx(txid, block_time, vin, vout):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": block_time},
        "vin": vin,
        "vout": vout,
    }


def _mock_gap_scan(used_on_receive, used_on_change):
    """Mock a gap scan where only index 0 is used on each of the two
    chains (used_on_receive/used_on_change are bools), and indexes 1-20
    are unused, so scanning stops right after the gap limit."""
    for chain, used_first in ((0, used_on_receive), (1, used_on_change)):
        responses.add(
            responses.GET,
            f"{API_BASE}/address/{derive_address(TEST_XPUB, chain, 0)}",
            json={"chain_stats": {"tx_count": 1 if used_first else 0}, "mempool_stats": {"tx_count": 0}},
            status=200,
        )
        for i in range(1, 21):
            responses.add(
                responses.GET,
                f"{API_BASE}/address/{derive_address(TEST_XPUB, chain, i)}",
                json={"chain_stats": {"tx_count": 0}, "mempool_stats": {"tx_count": 0}},
                status=200,
            )


def _mock_txs(address, txs):
    responses.add(responses.GET, f"{API_BASE}/address/{address}/txs", json=txs, status=200)


@responses.activate
def test_reports_incoming_transaction_on_a_discovered_receive_address():
    _mock_gap_scan(used_on_receive=True, used_on_change=False)
    incoming = _tx(
        "tx-in",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    _mock_txs(RECEIVE_0, [incoming])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.amount == Decimal("100000") / Decimal(10**8)
    assert tx.account_label == "ledger"
    assert tx.external_id == "tx-in"


@responses.activate
def test_internal_spend_and_change_to_owned_addresses_nets_to_zero_and_is_skipped():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    # A transaction that spends entirely from our receive address and sends
    # the change entirely back to our change address: no BTC actually left
    # the wallet, so it must NOT appear as a taxable transfer_out/transfer_in
    # pair -- this is the core correctness fix this whole feature is about.
    internal_move = _tx(
        "tx-internal",
        1700000100,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[{"scriptpubkey_address": CHANGE_0, "value": 199000}],  # 1000 sat fee, no external party
    )
    _mock_txs(RECEIVE_0, [internal_move])
    _mock_txs(CHANGE_0, [internal_move])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_spend_with_change_reports_only_the_true_external_outflow():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    # Spend 200000 sats from our receive address: 150000 goes to someone
    # else, 40000 comes back to our own change address, 10000 is fee.
    # True net outflow from the wallet as a whole: 150000 + 10000 = 160000
    # sats -- NOT 200000 (which would double-count the change as if it had
    # left the wallet too).
    spend = _tx(
        "tx-spend",
        1700000200,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[
            {"scriptpubkey_address": "someone-else", "value": 150000},
            {"scriptpubkey_address": CHANGE_0, "value": 40000},
        ],
    )
    _mock_txs(RECEIVE_0, [spend])
    _mock_txs(CHANGE_0, [spend])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("160000") / Decimal(10**8)
    assert tx.fee_amount == Decimal("10000") / Decimal(10**8)


@responses.activate
def test_a_transaction_seen_from_two_owned_addresses_is_only_reported_once():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    shared_tx = _tx(
        "tx-shared",
        1700000300,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[{"scriptpubkey_address": CHANGE_0, "value": 100000}],
    )
    # The same tx shows up when querying either owned address's tx list
    # (as it would in reality, via Blockstream's API) -- must be deduped.
    _mock_txs(RECEIVE_0, [shared_tx])
    _mock_txs(CHANGE_0, [shared_tx])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len([r for r in results if r.external_id == "tx-shared"]) <= 1


@responses.activate
def test_since_filters_out_older_transactions():
    _mock_gap_scan(used_on_receive=True, used_on_change=False)
    older = _tx(
        "tx-old",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    newer = _tx(
        "tx-new",
        1700001000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    _mock_txs(RECEIVE_0, [older, newer])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["tx-new"]


@responses.activate
def test_no_used_addresses_means_no_transactions_and_no_tx_fetch_calls():
    _mock_gap_scan(used_on_receive=False, used_on_change=False)

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert results == []
    txs_calls = [c for c in responses.calls if c.request.url.endswith("/txs")]
    assert len(txs_calls) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_bitcoin_xpub_adapter.py -v`
Expected: FAIL — `app/adapters/bitcoin_xpub.py` doesn't exist yet.

- [ ] **Step 3: Implement `app/adapters/bitcoin_xpub.py`**

```python
from datetime import datetime

from app.adapters.base import TransactionAdapter
from app.adapters.bitcoin import fetch_all_pages_for_address, normalize_bitcoin_tx
from app.adapters.bitcoin_gap_scan import discover_used_addresses
from app.schemas import NormalizedTransaction


class BitcoinXpubAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"

    def __init__(self, account_label: str, extended_key: str):
        super().__init__(account_label)
        self.extended_key = extended_key

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        owned_addresses = discover_used_addresses(self.extended_key)

        raw_txs_by_txid: dict[str, dict] = {}
        for address in owned_addresses:
            for tx in fetch_all_pages_for_address(address):
                raw_txs_by_txid[tx["txid"]] = tx

        results: list[NormalizedTransaction] = []
        for tx in raw_txs_by_txid.values():
            ntx = normalize_bitcoin_tx(tx, owned_addresses, self.account_label, since)
            if ntx is not None:
                results.append(ntx)
        return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_bitcoin_xpub_adapter.py -v`
Expected: PASS (7 tests).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/bitcoin_xpub.py KryptoWalletDashboard/backend/tests/test_bitcoin_xpub_adapter.py
git commit -m "feat: BitcoinXpubAdapter with correct wallet-level netting across discovered addresses"
```

---

### Task 5: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Write the failing test for `BITCOIN_XPUBS` parsing**

Append to `KryptoWalletDashboard/backend/tests/test_config.py`:
```python
def test_bitcoin_xpubs_reuses_wallet_parsing():
    from app.config import parse_wallets

    result = parse_wallets("ledger:xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8")

    assert len(result) == 1
    assert result[0].label == "ledger"
    assert result[0].address.startswith("xpub")
```

This confirms `parse_wallets()` (already used for `BITCOIN_ADDRESSES`/`ETHEREUM_ADDRESSES`) works unmodified for xpub strings too — no new parsing function needed, since an xpub/ypub/zpub string contains no `,` or `:` characters that would confuse the existing `label:address` splitter.

- [ ] **Step 2: Run the test to verify it passes immediately (this is a characterization test, not new behavior)**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS immediately — `parse_wallets` already exists and already handles this input correctly. This step exists to document/lock in that assumption, not to drive new implementation.

- [ ] **Step 3: Add the `BITCOIN_XPUBS` module constant to `app/config.py`**

Add alongside the existing `BITCOIN_WALLETS` constant in `KryptoWalletDashboard/backend/app/config.py`:
```python
BITCOIN_XPUBS = parse_wallets(os.getenv("BITCOIN_XPUBS"))
```

- [ ] **Step 4: Write the failing test for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_bitcoin_xpub_adapter_is_added_for_each_configured_xpub(monkeypatch):
    from app.adapters.bitcoin_xpub import BitcoinXpubAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(
        config,
        "BITCOIN_XPUBS",
        [WalletConfig(label="ledger", address="xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8")],
    )
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    xpub_adapters = [a for a in adapters if isinstance(a, BitcoinXpubAdapter)]
    assert len(xpub_adapters) == 1
    assert xpub_adapters[0].account_label == "ledger"
    assert xpub_adapters[0].extended_key.startswith("xpub")


def test_no_bitcoin_xpub_adapters_when_none_configured(monkeypatch):
    from app.adapters.bitcoin_xpub import BitcoinXpubAdapter

    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BitcoinXpubAdapter) for a in adapters)
```

Check `app/config.py` for the exact name of the `WalletConfig` dataclass (already used for `BITCOIN_WALLETS`/`ETHEREUM_WALLETS`) before writing this — the test above assumes it's called `WalletConfig` with `label`/`address` fields, matching the existing Phase 1 pattern; adjust only if it's actually named differently.

- [ ] **Step 5: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `build_adapters_from_config()` doesn't build any `BitcoinXpubAdapter` yet.

- [ ] **Step 6: Wire `BitcoinXpubAdapter` into `app/adapters/factory.py`**

Add the import:
```python
from app.adapters.bitcoin_xpub import BitcoinXpubAdapter
```

Add this block, near the existing loop that builds one `BitcoinAdapter` per `config.BITCOIN_WALLETS` entry (read the existing file first to match its exact loop style):
```python
    for wallet in config.BITCOIN_XPUBS:
        adapters.append(BitcoinXpubAdapter(account_label=wallet.label, extended_key=wallet.address))
```

- [ ] **Step 7: Run the new tests and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py tests/test_config.py -v`
Expected: PASS (all tests in both files, including the new ones).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 8: Commit**

```bash
git add KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/tests/test_config.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire BitcoinXpubAdapter into config and factory"
```

---

### Task 6: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document `BITCOIN_XPUBS` in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example`, right after the existing `BITCOIN_ADDRESSES` line:
```
# Bitcoin HD wallets (Ledger, Trezor, AtomicWallet, ...): give the wallet's
# extended public key (xpub/ypub/zpub - found in your wallet's "show xpub"
# or "account details" screen, NOT a single receive address) and every
# address that wallet has ever used is discovered and tracked automatically
# (gap-limit scanning, like every wallet app does internally). Comma-
# separated label:key pairs, same format as BITCOIN_ADDRESSES. Use this
# INSTEAD of BITCOIN_ADDRESSES for a whole HD wallet - use BITCOIN_ADDRESSES
# only for individual, fixed addresses you want to track on their own
# (e.g. a single exchange deposit address).
BITCOIN_XPUBS=ledger:zpub6jftahH1...
```

- [ ] **Step 2: Document xpub scanning in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, right after the existing Bitcoin-related setup content (find the right spot by reading the current file — likely near the top, close to where `BITCOIN_ADDRESSES` is first mentioned):
```markdown
### Bitcoin: einzelne Adressen vs. ganze HD-Wallets

`BITCOIN_ADDRESSES` verfolgt einzelne, fest eingetragene Adressen -
praktisch für z.B. eine einzelne Exchange-Einzahladresse, aber
unpraktisch für ein normales Wallet (Ledger, Trezor, AtomicWallet), das
für jede Transaktion eine neue Adresse generiert (HD-Wallet-Standard).

Für ein ganzes HD-Wallet stattdessen `BITCOIN_XPUBS` mit dem **Extended
Public Key** (xpub/ypub/zpub) des Wallets verwenden - zu finden in der
Wallet-Software unter "xpub anzeigen" / "Konto-Details" / "Erweiterte
öffentliche Adresse" (NICHT die einzelne Empfangsadresse, die die
Wallet-App standardmäßig anzeigt). Das Dashboard leitet daraus
automatisch alle bisher genutzten Adressen ab (Gap-Limit-Scanning,
Standard-Grenzwert 20 - wie bei jeder Wallet-Software) und erfasst deren
Transaktionen, inklusive korrekter Behandlung von Wechselgeld
(Change-Adressen): interne Verschiebungen zwischen Adressen desselben
Wallets werden nicht fälschlich als steuerrelevante Transaktion gezählt.

**Wichtig:** der Extended Public Key erlaubt zwar niemandem, deine
Bitcoins auszugeben (das geht nur mit dem privaten Schlüssel), macht
aber deine **gesamte Adresshistorie und alle Kontostände dieses
Wallets einsehbar** für jeden, der ihn kennt. Trotzdem vertraulich
behandeln wie ein Passwort.
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document BITCOIN_XPUBS and HD wallet gap-limit scanning"
```

---

## Self-Review Notes

- **Spec coverage:** shared normalization extraction + multi-address generalization (Task 1), BIP32 address derivation across all 3 formats (Task 2), gap-limit discovery (Task 3), the combining adapter with correct wallet-level netting and cross-address dedup (Task 4), config/factory wiring reusing the existing `parse_wallets` (Task 5), documentation including the privacy note about xpub sensitivity (Task 6). Matches the design doc's scope exactly.
- **Placeholder scan:** no TBD/TODO. The `bitcoinlib` API-verification steps in Task 2 are a deliberate, explicit research/verification gate (matching the established pattern for external library/API uncertainty in prior phases), not missing design work — the function *contract* is fully specified regardless of the exact internal `bitcoinlib` calls needed to satisfy it.
- **Type/signature consistency:** `derive_address(extended_key: str, chain: int, index: int) -> str` (Task 2) is used identically by `bitcoin_gap_scan.py` (Task 3) and indirectly relied upon by `bitcoin_xpub.py` (Task 4, via Task 3's `discover_used_addresses`). `normalize_bitcoin_tx(tx, owned_addresses: set[str], account_label, since)` (Task 1, generalized) is used identically by both `BitcoinAdapter` (a 1-element set) and `BitcoinXpubAdapter` (the full discovered set, Task 4) — no divergent copies of the netting logic exist anywhere. `fetch_all_pages_for_address(address: str)` (Task 1) is reused unchanged by `BitcoinXpubAdapter` (Task 4), called once per discovered address. `BitcoinXpubAdapter.__init__(self, account_label, extended_key)` (Task 4) matches exactly how `factory.py` constructs it (Task 5).
