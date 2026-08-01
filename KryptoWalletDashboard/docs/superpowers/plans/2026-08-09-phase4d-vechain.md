# Phase 4d – VeChain Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native VET and VIP-180-token (VeChain's ERC-20 equivalent, including explicit VTHO transfers) tracking for one or more fixed VeChain addresses — the last of the four originally-requested new chains (after Bitcoin xpub, Solana, Cardano).

**Architecture:** VeChainThor's official public Thorest API (`https://sync-mainnet.vechain.org`, free, no API key) is queried via plain REST POST. `/logs/transfer` returns discrete VET value movements directly (no UTXO netting needed, unlike Bitcoin/Cardano — VeChain addresses don't rotate, so this is a simple fixed-address adapter like Ethereum/Solana). `/logs/event` returns generic contract events, used to find VIP-180 `Transfer` events (identical event signature to ERC-20). A single VeChain transaction can contain multiple "clauses," each potentially containing multiple transfers, so `external_id` must be unique per individual transfer entry, not per transaction.

**Tech Stack:** Same as every prior on-chain adapter (Python, `requests`, `responses` for test mocking, pytest). No new dependency.

**Related docs:**
- [`docs/superpowers/specs/2026-08-09-phase4d-vechain-design.md`](../specs/2026-08-09-phase4d-vechain-design.md)

**Scope notes (decided during design, confirmed with user):**
- **VIP-180 tokens are included** (confirmed with user), reported with the raw contract address as `asset` (no symbol resolution) and a **simplifying assumption of 18 decimals for all VIP-180 tokens** — unlike Cardano's CNTs (where no decimals convention exists and raw integers are shown), VeChain's ecosystem overwhelmingly follows the EVM/ERC-20 18-decimal convention (VET and VTHO both use it), so defaulting to 18 decimals is a deliberate, documented trade-off favoring readability over the rare non-18-decimal token. **VTHO needs no special-casing** — it's itself a VIP-180 contract at a well-known fixed address (`0x0000000000000000000000000000456E65726779`) and flows through the exact same generic token-transfer logic as any other VIP-180 token.
- **No fee tracking.** VeChain's network fee is paid in VTHO, a completely different asset from whatever value is being transferred (VET or a VIP-180 token) — unlike Bitcoin/Solana/Cardano, the fee is never entangled with the transferred amount, so no fee-attribution logic is needed at all. VTHO consumed purely as gas (not explicitly transferred) is deliberately out of scope (would require an extra per-transaction receipt fetch) — only explicit VTHO *transfers* are tracked, via the generic VIP-180 path.
- **No address rotation, unlike Bitcoin/Cardano.** VeChain addresses are fixed (secp256k1-derived, same scheme as Ethereum) — a simple comma-separated address list (`VECHAIN_ADDRESSES`, reusing `parse_wallets`) is sufficient, no HD derivation or stake-address-style aggregation needed.
- **No swap-pairing**, matching the established convention for Bitcoin/Solana/Cardano — each asset movement is reported as an independent `transfer_in`/`transfer_out` leg.
- **`COINGECKO_ID_MAP` needs `"VET": "vechain"` and `"VTHO": "vethor-token"` entries** (Task 3) for CHF pricing of the two native-ish assets; other VIP-180 tokens remain unpriced.
- **API research caveat (elevated importance, same discipline as the Cardano phase):** Thorest API's exact `FilterRange`/`FilterOptions`/pagination field names, whether `criteriaSet` entries are genuinely OR-combined, and the exact `meta` object shape were **not fully confirmed** during design-time research. Given the Cardano phase found THREE real, silent-failure bugs via live-API verification that pure documentation reading missed, **Task 1 REQUIRES making real, live HTTP calls to `https://sync-mainnet.vechain.org` before finalizing any HTTP-calling code** — this is not optional, and is explicitly authorized to adjust anything in this plan's sketches that turns out to be wrong.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      vechain.py                # NEW — Thorest HTTP client, VeChainAdapter (VET + VIP-180)
      factory.py                    # MODIFIED — build VeChainAdapter per VECHAIN_ADDRESSES entry
    config.py                        # MODIFIED — VECHAIN_WALLETS (reuses existing parse_wallets)
    prices/
      coingecko.py                      # MODIFIED — add "VET"/"VTHO" to COINGECKO_ID_MAP
  .env.example                          # MODIFIED — document VECHAIN_ADDRESSES
  README.md                              # MODIFIED — document VeChain support and its limitations
  tests/
    test_vechain_adapter.py                 # NEW — all VeChain tests
    test_config.py                              # MODIFIED — VECHAIN_WALLETS parsing (characterization only)
    test_factory.py                                # MODIFIED — factory wiring
```

---

### Task 1: Thorest HTTP Client & Native VET Transfer Normalization

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/vechain.py`
- Create: `KryptoWalletDashboard/backend/tests/test_vechain_adapter.py`

**Data source:** `https://sync-mainnet.vechain.org`. `POST /logs/transfer` (body `{"criteriaSet": [{"sender": addr}, {"recipient": addr}], "order": "desc", "options": {"offset": ..., "limit": ...}}`) returns VET transfer log entries: `{"sender": "0x...", "recipient": "0x...", "amount": "0x...", "meta": {"blockTimestamp": ..., "txID": "0x...", "clauseIndex": ..., ...}}`.

### REQUIRED FIRST STEP — verify Thorest's actual API shape before writing HTTP-calling code

Before implementing anything, make real (unauthenticated, free, no API key needed) HTTP requests to `https://sync-mainnet.vechain.org` to confirm:
(a) `/logs/transfer`'s exact request body shape — does `criteriaSet` with two entries (`{"sender": addr}`, `{"recipient": addr}`) really OR them together? What are the correct `FilterOptions` field names for pagination (this plan assumes `offset`/`limit` inside an `options` object — verify)? Does `FilterRange` need to be included even when you don't want to filter by range, or can it be omitted entirely?
(b) The exact `meta` object field names on a real transfer log entry (this plan assumes `blockTimestamp` (unix seconds), `txID`, `clauseIndex` — verify all three, and check whether `blockTimestamp` might actually be milliseconds instead of seconds, or named differently).
(c) Whether `amount` is really a `0x`-prefixed hex string, and whether it can safely be parsed with Python's `int(value, 16)`.

You can verify this with a real, PUBLIC, well-known VeChain address — search for one referenced in public VeChain documentation, a well-known exchange hot wallet, or the VTHO/VET contract addresses themselves (`0x0000000000000000000000000000456E65726779` for VTHO is public knowledge and definitely has transaction history). Do NOT use or ask for a real user's private wallet address.

Concretely, try something like:
```python
import requests
resp = requests.post(
    "https://sync-mainnet.vechain.org/logs/transfer",
    json={
        "criteriaSet": [{"recipient": "<a real, public VeChain address>"}],
        "order": "desc",
        "options": {"offset": 0, "limit": 5},
    },
    timeout=15,
)
print(resp.status_code, resp.json())
```

**If Thorest's actual shape differs from this plan's assumptions**, adjust the implementation to match reality, and note exactly what you found and changed in your self-review — this mirrors the same verification discipline already used successfully (finding real bugs) for Koios in the Cardano phase.

**If you cannot reach the internet**, report NEEDS_CONTEXT immediately rather than guessing — a wrong assumption here would produce a subtly broken adapter that appears to work but silently returns wrong or no data.

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_vechain_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.vechain import VeChainAdapter

ADDR = "0x1234567890123456789012345678901234567890"
OTHER = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
API_URL = "https://sync-mainnet.vechain.org"


def _transfer_entry(sender, recipient, amount_wei, tx_id, clause_index, block_timestamp):
    return {
        "sender": sender,
        "recipient": recipient,
        "amount": hex(amount_wei),
        "meta": {
            "blockID": "0x" + "0" * 64,
            "blockNumber": 1,
            "blockTimestamp": block_timestamp,
            "txID": tx_id,
            "txOrigin": sender,
            "clauseIndex": clause_index,
        },
    }


def _mock_transfer_logs(result):
    responses.add(responses.POST, f"{API_URL}/logs/transfer", json=result, status=200)


def _mock_event_logs(result):
    responses.add(responses.POST, f"{API_URL}/logs/event", json=result, status=200)


@responses.activate
def test_incoming_vet_transfer_is_transfer_in():
    _mock_transfer_logs([_transfer_entry(OTHER, ADDR, 5 * 10**18, "0xtx1", 0, 1700000000)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    r = vet_results[0]
    assert r.tx_type == "transfer_in"
    assert r.amount == Decimal("5")


@responses.activate
def test_outgoing_vet_transfer_is_transfer_out():
    _mock_transfer_logs([_transfer_entry(ADDR, OTHER, 2 * 10**18, "0xtx2", 0, 1700000100)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    assert vet_results[0].tx_type == "transfer_out"
    assert vet_results[0].amount == Decimal("2")


@responses.activate
def test_self_transfer_is_skipped():
    _mock_transfer_logs([_transfer_entry(ADDR, ADDR, 1 * 10**18, "0xtx3", 0, 1700000200)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_zero_amount_transfer_is_skipped():
    _mock_transfer_logs([_transfer_entry(OTHER, ADDR, 0, "0xtx-zero", 0, 1700000250)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_since_filters_out_older_transfers():
    _mock_transfer_logs(
        [
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-old", 0, 1700000000),
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-new", 0, 1700001000),
        ]
    )
    _mock_event_logs([])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(since)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    assert vet_results[0].timestamp == datetime.fromtimestamp(1700001000, tz=timezone.utc)


@responses.activate
def test_multiple_transfers_in_the_same_clause_get_distinct_external_ids():
    _mock_transfer_logs(
        [
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-multi", 0, 1700000400),
            _transfer_entry(ADDR, OTHER, 1 * 10**18, "0xtx-multi", 0, 1700000400),
        ]
    )
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 2
    external_ids = {r.external_id for r in vet_results}
    assert len(external_ids) == 2, "both transfers must have distinct external_ids despite sharing tx+clause"


@responses.activate
def test_no_vet_transfers_returns_empty_list():
    _mock_transfer_logs([])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_vechain_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.vechain'`.

- [ ] **Step 3: Implement `app/adapters/vechain.py` (VET transfers; VIP-180 is stubbed for now)**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

API_URL = "https://sync-mainnet.vechain.org"
WEI_PER_VET = Decimal(10**18)
PAGE_LIMIT = 256


class VeChainAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "vechain"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        results.extend(self._fetch_vet_transfers(since))
        results.extend(self._fetch_vip180_transfers(since))
        return results

    def _fetch_vet_transfers(self, since) -> list[NormalizedTransaction]:
        entries = self._fetch_transfer_logs()
        results: list[NormalizedTransaction] = []
        index = 0
        for entry in entries:
            ntx = self._normalize_vet_entry(entry, since, index)
            if ntx is not None:
                results.append(ntx)
                index += 1
        return results

    def _fetch_transfer_logs(self) -> list[dict]:
        all_entries: list[dict] = []
        offset = 0
        while True:
            body = {
                "criteriaSet": [{"sender": self.address}, {"recipient": self.address}],
                "order": "desc",
                "options": {"offset": offset, "limit": PAGE_LIMIT},
            }
            response = requests.post(f"{API_URL}/logs/transfer", json=body, timeout=15)
            response.raise_for_status()
            page = response.json()
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return all_entries

    def _normalize_vet_entry(self, entry: dict, since, index: int) -> NormalizedTransaction | None:
        timestamp = datetime.fromtimestamp(entry["meta"]["blockTimestamp"], tz=timezone.utc)
        if since is not None and timestamp <= since:
            return None

        sender = entry["sender"]
        recipient = entry["recipient"]
        if sender.lower() == recipient.lower():
            return None

        amount_wei = int(entry["amount"], 16)
        if amount_wei == 0:
            return None

        if recipient.lower() == self.address.lower():
            tx_type = "transfer_in"
        elif sender.lower() == self.address.lower():
            tx_type = "transfer_out"
        else:
            return None

        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset="VET",
            amount=Decimal(amount_wei) / WEI_PER_VET,
            external_id=f"{entry['meta']['txID']}-{entry['meta']['clauseIndex']}-VET-{index}",
            raw_json=json.dumps(entry),
        )

    def _fetch_vip180_transfers(self, since) -> list[NormalizedTransaction]:
        # A later task fills this in.
        return []
```

**Remember the required verification step above** — adjust field names/shapes here to match what Thorest's live API actually returns, not just what's sketched here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_vechain_adapter.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/vechain.py KryptoWalletDashboard/backend/tests/test_vechain_adapter.py
git commit -m "feat: Thorest HTTP client and native VET transfer normalization"
```

---

### Task 2: VIP-180 Token Transfer Normalization (including VTHO)

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/vechain.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_vechain_adapter.py`

**Data source:** `POST /logs/event` (body `{"criteriaSet": [{"topic0": TRANSFER_SIG, "topic1": padded_addr}, {"topic0": TRANSFER_SIG, "topic2": padded_addr}], "order": "desc", "options": {...}}`) returns contract event entries: `{"address": "0x...(contract)", "topics": ["0x...(sig)", "0x...(padded sender)", "0x...(padded recipient)"], "data": "0x...(hex amount)", "meta": {"blockTimestamp": ..., "txID": ..., "clauseIndex": ..., ...}}`. The ERC-20/VIP-180 `Transfer(address,address,uint256)` event signature (topic0) is `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`.

**Verify this signature and the exact event-log shape against the live API too**, as part of this task's own testing (it wasn't covered by Task 1's required verification step, which only checked `/logs/transfer`) — e.g. query `/logs/event` filtering on the well-known VTHO contract address (`0x0000000000000000000000000000456E65726779`) with this topic0, which should reliably return real transfer events since VTHO is one of the most active contracts on the network.

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_vechain_adapter.py`:
```python
VTHO_CONTRACT = "0x0000000000000000000000000000456e65726779"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _padded_topic(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def _event_entry(contract, sender, recipient, amount, tx_id, clause_index, block_timestamp):
    return {
        "address": contract,
        "topics": [TRANSFER_TOPIC0, _padded_topic(sender), _padded_topic(recipient)],
        "data": hex(amount),
        "meta": {
            "blockID": "0x" + "0" * 64,
            "blockNumber": 1,
            "blockTimestamp": block_timestamp,
            "txID": tx_id,
            "txOrigin": sender,
            "clauseIndex": clause_index,
        },
    }


@responses.activate
def test_incoming_vip180_token_transfer_is_transfer_in():
    _mock_transfer_logs([])
    _mock_event_logs(
        [_event_entry(VTHO_CONTRACT, OTHER, ADDR, 10 * 10**18, "0xtx-vtho-in", 0, 1700000500)]
    )

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    token_results = [r for r in results if r.asset != "VET"]
    assert len(token_results) == 1
    r = token_results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == VTHO_CONTRACT
    assert r.amount == Decimal("10")


@responses.activate
def test_outgoing_vip180_token_transfer_is_transfer_out():
    _mock_transfer_logs([])
    _mock_event_logs(
        [_event_entry(VTHO_CONTRACT, ADDR, OTHER, 3 * 10**18, "0xtx-vtho-out", 0, 1700000600)]
    )

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    token_results = [r for r in results if r.asset != "VET"]
    assert len(token_results) == 1
    assert token_results[0].tx_type == "transfer_out"
    assert token_results[0].amount == Decimal("3")


@responses.activate
def test_vip180_self_transfer_is_skipped():
    _mock_transfer_logs([])
    _mock_event_logs([_event_entry(VTHO_CONTRACT, ADDR, ADDR, 1 * 10**18, "0xtx-self", 0, 1700000700)])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_vet_and_vip180_legs_in_one_tx_get_distinct_external_ids():
    _mock_transfer_logs([_transfer_entry(ADDR, OTHER, 1 * 10**18, "0xtx-combo", 0, 1700000800)])
    _mock_event_logs(
        [_event_entry(VTHO_CONTRACT, OTHER, ADDR, 5 * 10**18, "0xtx-combo", 1, 1700000800)]
    )

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert len(results) == 2
    external_ids = {r.external_id for r in results}
    assert len(external_ids) == 2
    vet_leg = next(r for r in results if r.asset == "VET")
    token_leg = next(r for r in results if r.asset != "VET")
    assert vet_leg.tx_type == "transfer_out"
    assert token_leg.tx_type == "transfer_in"


@responses.activate
def test_different_vip180_contracts_are_kept_separate():
    other_contract = "0x1111111111111111111111111111111111111a"
    _mock_transfer_logs([])
    _mock_event_logs(
        [
            _event_entry(VTHO_CONTRACT, OTHER, ADDR, 1 * 10**18, "0xtx-multi-token", 0, 1700000900),
            _event_entry(other_contract, OTHER, ADDR, 2 * 10**18, "0xtx-multi-token", 1, 1700000900),
        ]
    )

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assets = {r.asset for r in results}
    assert assets == {VTHO_CONTRACT, other_contract}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_vechain_adapter.py -v`
Expected: FAIL — the 5 new tests fail (`_fetch_vip180_transfers` still returns `[]` unconditionally).

- [ ] **Step 3: Implement VIP-180 normalization**

Replace the stub `_fetch_vip180_transfers` in `app/adapters/vechain.py`, and add the supporting pieces:
```python
TRANSFER_EVENT_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
```
(add near the other module constants)

```python
    def _fetch_vip180_transfers(self, since) -> list[NormalizedTransaction]:
        entries = self._fetch_event_logs()
        results: list[NormalizedTransaction] = []
        index = 0
        for entry in entries:
            ntx = self._normalize_vip180_entry(entry, since, index)
            if ntx is not None:
                results.append(ntx)
                index += 1
        return results

    def _fetch_event_logs(self) -> list[dict]:
        padded_address = "0x" + "0" * 24 + self.address[2:].lower()
        all_entries: list[dict] = []
        offset = 0
        while True:
            body = {
                "criteriaSet": [
                    {"topic0": TRANSFER_EVENT_TOPIC0, "topic1": padded_address},
                    {"topic0": TRANSFER_EVENT_TOPIC0, "topic2": padded_address},
                ],
                "order": "desc",
                "options": {"offset": offset, "limit": PAGE_LIMIT},
            }
            response = requests.post(f"{API_URL}/logs/event", json=body, timeout=15)
            response.raise_for_status()
            page = response.json()
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return all_entries

    def _normalize_vip180_entry(self, entry: dict, since, index: int) -> NormalizedTransaction | None:
        timestamp = datetime.fromtimestamp(entry["meta"]["blockTimestamp"], tz=timezone.utc)
        if since is not None and timestamp <= since:
            return None

        topics = entry["topics"]
        sender = "0x" + topics[1][-40:]
        recipient = "0x" + topics[2][-40:]
        if sender.lower() == recipient.lower():
            return None

        amount_raw = int(entry["data"], 16)
        if amount_raw == 0:
            return None

        if recipient.lower() == self.address.lower():
            tx_type = "transfer_in"
        elif sender.lower() == self.address.lower():
            tx_type = "transfer_out"
        else:
            return None

        contract = entry["address"]
        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset=contract,
            amount=Decimal(amount_raw) / WEI_PER_VET,
            external_id=f"{entry['meta']['txID']}-{entry['meta']['clauseIndex']}-{contract}-{index}",
            raw_json=json.dumps(entry),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_vechain_adapter.py -v`
Expected: PASS (12 tests: 7 from Task 1 + 5 new).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/vechain.py KryptoWalletDashboard/backend/tests/test_vechain_adapter.py
git commit -m "feat: VIP-180 token transfer normalization (VTHO included, no special-casing)"
```

---

### Task 3: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/app/prices/coingecko.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Add `VECHAIN_WALLETS` to `app/config.py`**

Add alongside the existing `CARDANO_WALLETS` constant:
```python
VECHAIN_WALLETS = parse_wallets(os.getenv("VECHAIN_ADDRESSES"))
```

No new config test needed — `parse_wallets` is already fully characterized by existing tests for other chains' identically-shaped config vars.

- [ ] **Step 2: Add `VET`/`VTHO` to `COINGECKO_ID_MAP`**

In `KryptoWalletDashboard/backend/app/prices/coingecko.py`, add to `COINGECKO_ID_MAP`:
```python
    "VET": "vechain",
    "VTHO": "vethor-token",
```

- [ ] **Step 3: Write the failing tests for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_vechain_adapter_is_added_for_each_configured_address(monkeypatch):
    from app.adapters.vechain import VeChainAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(config, "VECHAIN_WALLETS", [WalletConfig(label="main", address="0xabc")])
    monkeypatch.setattr(config, "CARDANO_WALLETS", [])
    monkeypatch.setattr(config, "CARDANO_STAKE_WALLETS", [])
    monkeypatch.setattr(config, "SOLANA_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
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

    vechain_adapters = [a for a in adapters if isinstance(a, VeChainAdapter)]
    assert len(vechain_adapters) == 1
    assert vechain_adapters[0].account_label == "main"
    assert vechain_adapters[0].address == "0xabc"


def test_no_vechain_adapters_when_none_configured(monkeypatch):
    from app.adapters.vechain import VeChainAdapter

    monkeypatch.setattr(config, "VECHAIN_WALLETS", [])
    monkeypatch.setattr(config, "CARDANO_WALLETS", [])
    monkeypatch.setattr(config, "CARDANO_STAKE_WALLETS", [])
    monkeypatch.setattr(config, "SOLANA_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "BITCOIN_XPUBS", [])
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

    assert not any(isinstance(a, VeChainAdapter) for a in adapters)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `build_adapters_from_config()` doesn't build any `VeChainAdapter` yet.

- [ ] **Step 5: Wire `VeChainAdapter` into `app/adapters/factory.py`**

Add the import:
```python
from app.adapters.vechain import VeChainAdapter
```

Add this block, near the existing `config.SOLANA_WALLETS`/`config.CARDANO_WALLETS` loops:
```python
    for wallet in config.VECHAIN_WALLETS:
        adapters.append(VeChainAdapter(account_label=wallet.label, address=wallet.address))
```

- [ ] **Step 6: Run the new tests and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/app/prices/coingecko.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire VeChainAdapter into config and factory, add VET/VTHO to CoinGecko price map"
```

---

### Task 4: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document `VECHAIN_ADDRESSES` in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example`, after the existing Cardano entries:
```
# VeChain: comma-separated label:address pairs. Addresses are fixed
# (same secp256k1 scheme as Ethereum) - no address rotation, so unlike
# Bitcoin/Cardano, one entry per account is enough.
VECHAIN_ADDRESSES=main:0xYourVeChainAddressHere...
```

- [ ] **Step 2: Document VeChain support and its limitations in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, after the existing Cardano section:
```markdown
## VeChain

Native VET- und VIP-180-Token-Transfers (VeChains ERC-20-Äquivalent,
inkl. expliziter VTHO-Transfers) werden automatisch erfasst, sobald
`VECHAIN_ADDRESSES` gesetzt ist. VeChain-Adressen sind fest (dasselbe
Adressschema wie Ethereum) - keine Adressrotation wie bei Bitcoin/
Cardano, eine Adresse pro Konto reicht.

**Keine Gebühren-Erfassung:** VeChains Netzwerkgebühr wird in VTHO
bezahlt - einem komplett anderen Asset als der transferierte Wert (VET
oder ein VIP-180-Token). Die Gebühr ist daher nie im gemeldeten Betrag
verflochten (anders als bei Bitcoin). VTHO, das rein als Netzwerkgebühr
verbraucht wird (nicht explizit transferiert), wird **nicht** erfasst -
nur explizite VTHO-*Transfers* (z.B. jemand sendet dir VTHO) werden wie
jeder andere VIP-180-Token erfasst.

### Bekannte Einschränkung: VIP-180-Tokens ohne Symbol/CHF-Kurs, feste Dezimalstellen-Annahme

VIP-180-Token-Transfers werden vollständig erfasst (Menge, Zeitpunkt,
Richtung), aber ohne lesbaren Namen (nur die Contract-Adresse als roher
Bezeichner) und ohne CHF-Kurs (analog zur bestehenden Einschränkung bei
ERC-20/SPL-Tokens). Zusätzlich wird für **alle** VIP-180-Tokens
pauschal von **18 Dezimalstellen** ausgegangen (wie bei VET/VTHO und
der überwiegenden Mehrheit der VeChain-Ökosystem-Tokens) - ein seltener
Token mit abweichender Dezimalstellen-Zahl würde falsch skaliert
angezeigt. Für die Steuererklärung im Zweifel gegen einen
VeChain-Explorer wie vechainstats.com verifizieren.
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document VeChain support, VET/VIP-180 handling, and known limitations"
```

---

## Self-Review Notes

- **Spec coverage:** Thorest HTTP client + VET normalization with mandatory live-API verification (Task 1), VIP-180/VTHO normalization with no special-casing (Task 2), config/factory wiring plus `COINGECKO_ID_MAP` entries (Task 3), documentation including the fee/decimals limitations (Task 4). Matches the design doc's scope exactly, including the confirmed user decision to include VIP-180 tokens.
- **Placeholder scan:** no TBD/TODO. The elevated "API research caveat" (a required, not optional, live-verification step) is a deliberate constraint reflecting the same genuine uncertainty that proved valuable to check explicitly in the Cardano phase — not missing design work.
- **Type/signature consistency:** `VeChainAdapter.__init__(self, account_label, address)` is fixed from its first commit (Task 1) and matches exactly how `factory.py` constructs it (Task 3). `_normalize_vet_entry`/`_normalize_vip180_entry` both take `(entry, since, index)` and return `NormalizedTransaction | None`, called from their respective `_fetch_*_transfers` methods identically. `PAGE_LIMIT`/`WEI_PER_VET`/`API_URL` (Task 1) are reused unchanged by Task 2's event-log fetching, no duplicated constants.
