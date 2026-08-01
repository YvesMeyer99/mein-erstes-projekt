# Phase 4c – Cardano Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native ADA and Cardano-native-token (CNT) transfer tracking, via two adapters — `CardanoAdapter` for a single fixed address, and `CardanoStakeAdapter` for a stake address (which the free public Koios API automatically resolves to every payment address ever used under it, solving Cardano's HD-address-rotation problem without any client-side derivation).

**Architecture:** The Koios community API (`https://api.koios.rest/api/v1`, free, no API key) is queried via plain REST GET/POST. `/account_txs` (GET, stake address) and `/address_txs` (POST, payment addresses) both return lists of transaction hashes with block times; `/tx_info` (POST, batch of hashes) returns full UTXO detail (inputs/outputs with addresses, lovelace values, and native-token `asset_list`s). `/account_addresses` (POST, stake addresses) resolves a stake address to every payment address that belongs to it — this is what lets `CardanoStakeAdapter` avoid Bitcoin-style gap-limit scanning entirely. Both adapters share one normalization function, `normalize_cardano_tx`, built around the same `owned_addresses: set[str]` pattern already proven for `BitcoinAdapter`/`BitcoinXpubAdapter` — including, this time, the "fully-internal-transfer" skip built in from the very first commit (Phase 4a needed a follow-up fix to add this; this plan applies that lesson from the start).

**Tech Stack:** Same as every prior on-chain adapter (Python, `requests`, `responses` for test mocking, pytest). No new dependency — Koios is plain JSON REST, no signing, no client-side cryptography needed (unlike Bitcoin's `bitcoinlib`).

**Related docs:**
- [`docs/superpowers/specs/2026-08-08-phase4c-cardano-design.md`](../specs/2026-08-08-phase4c-cardano-design.md)

**Scope notes (decided during design, confirmed with user):**
- **Both `CARDANO_ADDRESSES` (single fixed addresses) and `CARDANO_STAKE_ADDRESSES` (stake-address aggregation) are supported**, mirroring Bitcoin's `BITCOIN_ADDRESSES`/`BITCOIN_XPUBS` split — confirmed with the user, who chose "both" specifically to avoid repeating the address-rotation problem already hit with Bitcoin/Ledger.
- **Native tokens (CNTs) are included**, reported as a raw `f"{policy_id}{asset_name}"` identifier (no symbol resolution) with the **raw on-chain integer quantity, unadjusted for decimals** — Cardano has no protocol-level decimals field for native tokens (unlike SPL's per-mint `decimals`); resolving human-readable amounts would need an external metadata registry, out of scope (confirmed with user, same YAGNI reasoning already accepted for ERC-20/SPL).
- **The "fully internal transfer" skip (all inputs AND all outputs belong to `owned_addresses` → skip, don't report even the fee as a fake transfer) is implemented from Task 1**, not discovered later via TDD — this is a deliberate improvement over how Phase 4a (Bitcoin xpub) actually unfolded, where the equivalent bug was found and fixed mid-plan. Task 1's own tests must include this case from the start.
- **`COINGECKO_ID_MAP` needs an `"ADA": "cardano"` entry** (Task 4) for CHF pricing of native ADA; native tokens remain unpriced per the limitation above.
- **No RPC retry/backoff for rate limits** — matches the already-accepted precedent from Bitcoin/Solana (public endpoint, occasional manual sync; Koios's rate limit — 100 requests/10s per IP — is generous for this use case anyway).
- **API research caveat (elevated importance for this plan):** Koios's exact `/tx_info` response shape — specifically whether a UTXO's address is a plain string (`"payment_addr": "addr1..."`) or a nested object (`"payment_addr": {"bech32": "addr1..."}`) — was **not fully confirmed** during design-time research (the OpenAPI spec file was too large to fetch in full). Task 1 makes a best-effort assumption (the nested-object form, `_extract_address()` helper) but Task 2 REQUIRES an explicit verification step against Koios's actual live response before finalizing the HTTP-calling code — and is explicitly authorized to adjust Task 1's `_extract_address()`/`normalize_cardano_tx()` if the real shape differs. This mirrors the same "verify library/API behavior interactively before trusting the plan's sketch" pattern already used successfully for `bitcoinlib` in Phase 4a.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      cardano.py               # NEW — normalize_cardano_tx, Koios HTTP client, CardanoAdapter, CardanoStakeAdapter
      factory.py                   # MODIFIED — build both Cardano adapters per config
    config.py                        # MODIFIED — CARDANO_WALLETS, CARDANO_STAKE_WALLETS (reuse parse_wallets)
    prices/
      coingecko.py                     # MODIFIED — add "ADA": "cardano" to COINGECKO_ID_MAP
  .env.example                          # MODIFIED — document CARDANO_ADDRESSES / CARDANO_STAKE_ADDRESSES
  README.md                              # MODIFIED — document Cardano support and its limitations
  tests/
    test_cardano_adapter.py                 # NEW — all Cardano tests (normalization, HTTP client, both adapters)
    test_config.py                              # MODIFIED — CARDANO_WALLETS/CARDANO_STAKE_WALLETS parsing
    test_factory.py                                # MODIFIED — factory wiring
```

---

### Task 1: Shared Cardano Transaction Normalization

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/cardano.py`
- Create: `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`

**Scope:** a pure, HTTP-free function `normalize_cardano_tx(tx: dict, owned_addresses: set[str], account_label: str, since: datetime | None) -> list[NormalizedTransaction]` that takes ONE already-fetched transaction-detail dict (the shape Koios's `/tx_info` is expected to return — see the caveat above) and returns zero or more `NormalizedTransaction`s (one ADA leg if ADA moved, one leg per native token that moved). No network calls in this task — `CardanoAdapter`/`CardanoStakeAdapter` (Tasks 2-3) call this after fetching real data.

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.cardano import normalize_cardano_tx

ADDR = "addr1qxy2lpan99fcnhhwz097erhm0k5m2gce8hcx6ycpwslzcxwgtpsxx4qkumaq"
OTHER = "addr1qother0000000000000000000000000000000000000000000000000000"
CHANGE = "addr1qchange00000000000000000000000000000000000000000000000000"


def _utxo(address, value, asset_list=None):
    return {"payment_addr": {"bech32": address}, "value": str(value), "asset_list": asset_list or []}


def _tx(tx_hash, timestamp, inputs, outputs, fee="170000"):
    return {"tx_hash": tx_hash, "tx_timestamp": timestamp, "fee": fee, "inputs": inputs, "outputs": outputs}


def test_incoming_ada_transfer_is_transfer_in():
    tx = _tx(
        "tx-in",
        1700000000,
        inputs=[_utxo(OTHER, 2000000)],
        outputs=[_utxo(ADDR, 1000000), _utxo(OTHER, 800000)],
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == "ADA"
    assert r.amount == Decimal("1000000") / Decimal(10**6)
    assert r.fee_amount is None
    assert r.external_id == "tx-in-ADA"
    assert r.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_outgoing_ada_transfer_includes_fee():
    tx = _tx(
        "tx-out",
        1700000100,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[_utxo(OTHER, 1830000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("2000000") / Decimal(10**6)
    assert r.fee_amount == Decimal("170000") / Decimal(10**6)
    assert r.fee_asset == "ADA"


def test_change_to_a_different_owned_address_nets_correctly():
    # Spend 2,000,000 lovelace from ADDR: 1,500,000 to OTHER, 330,000 back
    # as change to CHANGE (also ours, e.g. resolved via a stake address),
    # 170,000 fee. True net outflow: 1,500,000 + 170,000 = 1,670,000 --
    # NOT 2,000,000 (which would double-count the change as if it left).
    tx = _tx(
        "tx-change",
        1700000200,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[_utxo(OTHER, 1500000), _utxo(CHANGE, 330000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR, CHANGE}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("1670000") / Decimal(10**6)
    assert r.fee_amount == Decimal("170000") / Decimal(10**6)


def test_fully_internal_transfer_with_fee_is_skipped_entirely():
    # Every input AND every output belongs to owned_addresses -- a pure
    # wallet-internal reshuffle. No ADA left the wallet as a whole; only
    # the network fee did, which is not treated as a taxable transfer_out
    # here (same reasoning as app/adapters/bitcoin.py's identical check).
    tx = _tx(
        "tx-internal",
        1700000300,
        inputs=[_utxo(ADDR, 1000000)],
        outputs=[_utxo(CHANGE, 830000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR, CHANGE}, "main", None)

    assert results == []


def test_zero_net_change_produces_no_ada_entry():
    tx = _tx("tx-noop", 1700000400, inputs=[_utxo(OTHER, 1000000)], outputs=[_utxo(OTHER, 830000)])

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert results == []


def test_incoming_native_token_transfer_is_transfer_in():
    tx = _tx(
        "tx-token-in",
        1700000500,
        inputs=[_utxo(OTHER, 2000000)],
        outputs=[
            _utxo(
                ADDR,
                1200000,
                asset_list=[{"policy_id": "abcd1234", "asset_name": "484f534b59", "quantity": "500"}],
            ),
            _utxo(OTHER, 700000),
        ],
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    token_results = [r for r in results if r.asset != "ADA"]
    assert len(token_results) == 1
    r = token_results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == "abcd1234484f534b59"
    assert r.amount == Decimal("500")
    assert r.external_id == "tx-token-in-abcd1234484f534b59"


def test_ada_and_token_legs_in_one_tx_get_distinct_external_ids():
    tx = _tx(
        "tx-swap",
        1700000600,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[
            _utxo(OTHER, 1830000),
            _utxo(ADDR, 0, asset_list=[{"policy_id": "abcd1234", "asset_name": "484f534b59", "quantity": "100"}]),
        ],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 2
    external_ids = {r.external_id for r in results}
    assert external_ids == {"tx-swap-ADA", "tx-swap-abcd1234484f534b59"}
    ada_leg = next(r for r in results if r.asset == "ADA")
    token_leg = next(r for r in results if r.asset != "ADA")
    assert ada_leg.tx_type == "transfer_out"
    assert token_leg.tx_type == "transfer_in"


def test_since_filters_out_older_transactions():
    tx = _tx("tx-old", 1700000000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = normalize_cardano_tx(tx, {ADDR}, "main", since)

    assert results == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.cardano'`.

- [ ] **Step 3: Implement `app/adapters/cardano.py` (normalization only for now)**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas import NormalizedTransaction

LOVELACE_PER_ADA = Decimal(10**6)


def _extract_address(utxo: dict) -> str | None:
    """Koios's payment address field shape was not fully confirmed during
    design-time research -- this defensively supports both a nested
    {"bech32": "addr1..."} object and a plain "addr1..." string. Verify
    against Koios's actual live response in Task 2/3 and simplify this if
    only one shape is ever seen in practice."""
    addr = utxo.get("payment_addr")
    if isinstance(addr, dict):
        return addr.get("bech32")
    return addr


def normalize_cardano_tx(
    tx: dict,
    owned_addresses: set[str],
    account_label: str,
    since: datetime | None,
) -> list[NormalizedTransaction]:
    timestamp = datetime.fromtimestamp(tx["tx_timestamp"], tz=timezone.utc)
    if since is not None and timestamp <= since:
        return []

    input_addrs = {_extract_address(i) for i in tx["inputs"]}
    output_addrs = {_extract_address(o) for o in tx["outputs"]}
    if input_addrs <= owned_addresses and output_addrs <= owned_addresses:
        # Fully internal wallet reshuffle: no ADA left the wallet as a
        # whole, only the network fee did -- not treated as a taxable
        # transfer here. Same reasoning as app/adapters/bitcoin.py's
        # identical check (added there only after a later review found the
        # gap; built in here from the start).
        return []

    results: list[NormalizedTransaction] = []

    ada_in = sum(
        Decimal(o["value"]) for o in tx["outputs"] if _extract_address(o) in owned_addresses
    )
    ada_out = sum(
        Decimal(i["value"]) for i in tx["inputs"] if _extract_address(i) in owned_addresses
    )
    net_lovelace = ada_in - ada_out
    if net_lovelace != 0:
        fee_amount = None
        fee_asset = None
        if net_lovelace < 0:
            fee_amount = Decimal(tx["fee"]) / LOVELACE_PER_ADA
            fee_asset = "ADA"
        results.append(
            NormalizedTransaction(
                timestamp=timestamp,
                source_type="chain",
                source_name="cardano",
                account_label=account_label,
                tx_type="transfer_in" if net_lovelace > 0 else "transfer_out",
                asset="ADA",
                amount=abs(net_lovelace) / LOVELACE_PER_ADA,
                fee_amount=fee_amount,
                fee_asset=fee_asset,
                external_id=f"{tx['tx_hash']}-ADA",
                raw_json=json.dumps(tx),
            )
        )

    results.extend(_normalize_native_tokens(tx, owned_addresses, account_label, timestamp))
    return results


def _normalize_native_tokens(
    tx: dict, owned_addresses: set[str], account_label: str, timestamp
) -> list[NormalizedTransaction]:
    net_by_asset: dict[str, Decimal] = {}
    for output in tx["outputs"]:
        if _extract_address(output) not in owned_addresses:
            continue
        for asset in output.get("asset_list", []):
            key = f"{asset['policy_id']}{asset['asset_name']}"
            net_by_asset[key] = net_by_asset.get(key, Decimal(0)) + Decimal(asset["quantity"])
    for inp in tx["inputs"]:
        if _extract_address(inp) not in owned_addresses:
            continue
        for asset in inp.get("asset_list", []):
            key = f"{asset['policy_id']}{asset['asset_name']}"
            net_by_asset[key] = net_by_asset.get(key, Decimal(0)) - Decimal(asset["quantity"])

    results: list[NormalizedTransaction] = []
    for key, net in net_by_asset.items():
        if net == 0:
            continue
        results.append(
            NormalizedTransaction(
                timestamp=timestamp,
                source_type="chain",
                source_name="cardano",
                account_label=account_label,
                tx_type="transfer_in" if net > 0 else "transfer_out",
                asset=key,
                amount=abs(net),
                external_id=f"{tx['tx_hash']}-{key}",
                raw_json=json.dumps(tx),
            )
        )
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/cardano.py KryptoWalletDashboard/backend/tests/test_cardano_adapter.py
git commit -m "feat: shared Cardano transaction normalization with internal-transfer skip built in"
```

---

### Task 2: Koios HTTP Client & `CardanoAdapter` (Single Address)

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/cardano.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`

**Data source:** `https://api.koios.rest/api/v1`. `POST /address_txs` (body `{"_addresses": [...], "_after_block_height": ...}`) returns `[{"tx_hash": ..., "block_height": ..., "block_time": ...}, ...]`. `POST /tx_info` (body `{"_tx_hashes": [...]}`) returns full transaction details in the shape `normalize_cardano_tx` (Task 1) expects. Pagination: Koios (PostgREST-based) uses `limit`/`offset` query-string parameters, capped at 1000 rows per page, for both GET and POST endpoints.

**REQUIRED FIRST STEP — verify Koios's actual API shape before writing HTTP-calling code:**

Before implementing, make a real (unauthenticated, free) HTTP request to Koios to confirm: (a) `/tx_info`'s actual `payment_addr` field shape (plain string vs. `{"bech32": "..."}` object — Task 1's `_extract_address()` was written defensively for both, but confirm which one Koios actually returns so you know the defensive branch isn't hiding a mismatch), (b) the exact field name for the transaction timestamp in `/tx_info`'s response (this plan assumes `tx_timestamp`; if Koios actually calls it something else, e.g. `block_time`, you'll need to adjust `normalize_cardano_tx` in Task 1's already-committed code), and (c) `/address_txs`'s exact request/response shape. You can do this with a real, public, well-known Cardano address (e.g. search for "cardano foundation treasury address" or use any address you can find referenced publicly — do NOT use a real user's private address for this check) via `curl` or a quick Python script using `requests`. If Koios's actual shape differs from this plan's assumptions, fix `app/adapters/cardano.py` (including, if needed, amending Task 1's `normalize_cardano_tx`/`_extract_address` — this is explicitly authorized) to match reality, and note exactly what you found and changed in your self-review. This mirrors the same verification discipline already used successfully for `bitcoinlib` in the Bitcoin xpub phase.

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`:
```python
import responses

from app.adapters.cardano import CardanoAdapter

API_URL = "https://api.koios.rest/api/v1"


def _sig(tx_hash, block_time):
    return {"tx_hash": tx_hash, "block_height": 1, "block_time": block_time}


def _mock_address_txs(result):
    responses.add(responses.POST, f"{API_URL}/address_txs", json=result, status=200)


def _mock_tx_info(result):
    responses.add(responses.POST, f"{API_URL}/tx_info", json=result, status=200)


@responses.activate
def test_cardano_adapter_fetches_and_normalizes_transactions():
    _mock_address_txs([_sig("tx-in", 1700000000)])
    _mock_tx_info(
        [_tx("tx-in", 1700000000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000), _utxo(OTHER, 800000)])]
    )

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "transfer_in"
    assert results[0].amount == Decimal("1000000") / Decimal(10**6)


@responses.activate
def test_cardano_adapter_no_transactions_means_no_tx_info_call():
    _mock_address_txs([])

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
    tx_info_calls = [c for c in responses.calls if c.request.url.endswith("/tx_info")]
    assert len(tx_info_calls) == 0


@responses.activate
def test_cardano_adapter_since_excludes_old_signatures_from_tx_info_call():
    _mock_address_txs([_sig("tx-old", 1700000000), _sig("tx-new", 1700001000)])
    _mock_tx_info(
        [_tx("tx-new", 1700001000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])]
    )

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-new-ADA"]
    tx_info_call = next(c for c in responses.calls if c.request.url.endswith("/tx_info"))
    import json as _json

    sent_hashes = _json.loads(tx_info_call.request.body)["_tx_hashes"]
    assert sent_hashes == ["tx-new"]


@responses.activate
def test_cardano_adapter_paginates_address_txs_until_short_page():
    full_page = [_sig(f"tx-{i}", 1700000000 + i) for i in range(1000)]
    short_page = [_sig("tx-last", 1700002000)]
    _mock_address_txs(full_page)
    _mock_address_txs(short_page)
    _mock_tx_info([])

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    adapter.fetch_transactions(None)

    address_txs_calls = [c for c in responses.calls if c.request.url.split("?")[0].endswith("/address_txs")]
    assert len(address_txs_calls) == 2
```

Note: `_tx`/`_utxo`/`ADDR`/`OTHER` already exist from Task 1 at module scope in this test file — reuse them, don't redefine.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: FAIL — `CardanoAdapter` doesn't exist yet.

- [ ] **Step 3: Implement the Koios HTTP client and `CardanoAdapter` in `app/adapters/cardano.py`**

Add to `app/adapters/cardano.py` (after the existing normalization functions from Task 1 — do not remove or restructure those, only append):
```python
import requests

from app.adapters.base import TransactionAdapter

API_URL = "https://api.koios.rest/api/v1"
PAGE_LIMIT = 1000


def _koios_post(path: str, body: dict) -> list:
    response = requests.post(f"{API_URL}{path}", json=body, timeout=10)
    response.raise_for_status()
    return response.json()


def _fetch_tx_infos(tx_hashes: list[str]) -> list[dict]:
    if not tx_hashes:
        return []
    all_tx_infos: list[dict] = []
    for i in range(0, len(tx_hashes), PAGE_LIMIT):
        chunk = tx_hashes[i : i + PAGE_LIMIT]
        all_tx_infos.extend(_koios_post("/tx_info", {"_tx_hashes": chunk}))
    return all_tx_infos


class CardanoAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "cardano"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since) -> list[NormalizedTransaction]:
        candidates = self._fetch_candidate_signatures(since)
        if not candidates:
            return []
        tx_infos = _fetch_tx_infos([c["tx_hash"] for c in candidates])
        results: list[NormalizedTransaction] = []
        for tx in tx_infos:
            results.extend(normalize_cardano_tx(tx, {self.address}, self.account_label, since))
        return results

    def _fetch_candidate_signatures(self, since) -> list[dict]:
        all_entries: list[dict] = []
        offset = 0
        while True:
            page = _koios_post(
                "/address_txs", {"_addresses": [self.address], "limit": PAGE_LIMIT, "offset": offset}
            )
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT

        if since is None:
            return all_entries
        return [
            e for e in all_entries
            if datetime.fromtimestamp(e["block_time"], tz=timezone.utc) > since
        ]
```

**Remember the required verification step above** — adjust field names/shapes here (and in Task 1's already-committed `normalize_cardano_tx`/`_extract_address` if needed) to match what Koios's live API actually returns, not just what's sketched here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: PASS (13 tests: 9 from Task 1 + 4 new).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/cardano.py KryptoWalletDashboard/backend/tests/test_cardano_adapter.py
git commit -m "feat: Koios HTTP client and CardanoAdapter for single fixed addresses"
```

---

### Task 3: `CardanoStakeAdapter` (Stake Address)

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/cardano.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`

**Data source:** `POST /account_addresses` (body `{"_stake_addresses": [...]}`) resolves a stake address to every payment address that belongs to it, returning `[{"stake_address": "stake1...", "addresses": ["addr1...", "addr1...", ...]}]`. `GET /account_txs` (`_stake_address=stake1...`, `limit`/`offset`) returns the same `{tx_hash, block_height, block_time}` shape as `/address_txs`, but already aggregated across every payment address under that stake key — no client-side HD derivation or gap-limit scanning needed.

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_cardano_adapter.py`:
```python
from app.adapters.cardano import CardanoStakeAdapter

STAKE_ADDR = "stake1uxyz0000000000000000000000000000000000000000000000000000"


def _mock_account_addresses(stake_address, addresses):
    responses.add(
        responses.POST,
        f"{API_URL}/account_addresses",
        json=[{"stake_address": stake_address, "addresses": addresses}],
        status=200,
    )


def _mock_account_txs(result):
    responses.add(responses.GET, f"{API_URL}/account_txs", json=result, status=200)


@responses.activate
def test_cardano_stake_adapter_resolves_addresses_and_nets_across_all_of_them():
    _mock_account_addresses(STAKE_ADDR, [ADDR, CHANGE])
    _mock_account_txs([_sig("tx-change", 1700000200)])
    _mock_tx_info(
        [
            _tx(
                "tx-change",
                1700000200,
                inputs=[_utxo(ADDR, 2000000)],
                outputs=[_utxo(OTHER, 1500000), _utxo(CHANGE, 330000)],
                fee="170000",
            )
        ]
    )

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("1670000") / Decimal(10**6)


@responses.activate
def test_cardano_stake_adapter_internal_transfer_between_resolved_addresses_is_skipped():
    _mock_account_addresses(STAKE_ADDR, [ADDR, CHANGE])
    _mock_account_txs([_sig("tx-internal", 1700000300)])
    _mock_tx_info(
        [_tx("tx-internal", 1700000300, inputs=[_utxo(ADDR, 1000000)], outputs=[_utxo(CHANGE, 830000)], fee="170000")]
    )

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_cardano_stake_adapter_no_transactions_means_no_tx_info_call():
    _mock_account_addresses(STAKE_ADDR, [ADDR])
    _mock_account_txs([])

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
    tx_info_calls = [c for c in responses.calls if c.request.url.endswith("/tx_info")]
    assert len(tx_info_calls) == 0


@responses.activate
def test_cardano_stake_adapter_since_excludes_old_transactions():
    _mock_account_addresses(STAKE_ADDR, [ADDR])
    _mock_account_txs([_sig("tx-old", 1700000000), _sig("tx-new", 1700001000)])
    _mock_tx_info([_tx("tx-new", 1700001000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-new-ADA"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: FAIL — `CardanoStakeAdapter` doesn't exist yet.

- [ ] **Step 3: Implement `CardanoStakeAdapter`**

Add to `app/adapters/cardano.py`:
```python
class CardanoStakeAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "cardano"

    def __init__(self, account_label: str, stake_address: str):
        super().__init__(account_label)
        self.stake_address = stake_address

    def fetch_transactions(self, since) -> list[NormalizedTransaction]:
        owned_addresses = self._resolve_owned_addresses()
        candidates = self._fetch_candidate_signatures(since)
        if not candidates:
            return []
        tx_infos = _fetch_tx_infos([c["tx_hash"] for c in candidates])
        results: list[NormalizedTransaction] = []
        for tx in tx_infos:
            results.extend(normalize_cardano_tx(tx, owned_addresses, self.account_label, since))
        return results

    def _resolve_owned_addresses(self) -> set[str]:
        rows = _koios_post("/account_addresses", {"_stake_addresses": [self.stake_address]})
        if not rows:
            return set()
        return set(rows[0].get("addresses", []))

    def _fetch_candidate_signatures(self, since) -> list[dict]:
        all_entries: list[dict] = []
        offset = 0
        while True:
            response = requests.get(
                f"{API_URL}/account_txs",
                params={"_stake_address": self.stake_address, "limit": PAGE_LIMIT, "offset": offset},
                timeout=10,
            )
            response.raise_for_status()
            page = response.json()
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT

        if since is None:
            return all_entries
        return [
            e for e in all_entries
            if datetime.fromtimestamp(e["block_time"], tz=timezone.utc) > since
        ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_cardano_adapter.py -v`
Expected: PASS (17 tests: 13 from Task 2 + 4 new).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/cardano.py KryptoWalletDashboard/backend/tests/test_cardano_adapter.py
git commit -m "feat: CardanoStakeAdapter resolves all payment addresses via a stake address"
```

---

### Task 4: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/app/prices/coingecko.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Add `CARDANO_WALLETS`/`CARDANO_STAKE_WALLETS` to `app/config.py`**

Add alongside the existing `SOLANA_WALLETS` constant:
```python
CARDANO_WALLETS = parse_wallets(os.getenv("CARDANO_ADDRESSES"))
CARDANO_STAKE_WALLETS = parse_wallets(os.getenv("CARDANO_STAKE_ADDRESSES"))
```

No new test needed for the parsing itself — `parse_wallets` is already characterized by existing tests (`test_bitcoin_xpubs_reuses_wallet_parsing`, `test_solana_wallets_reuses_wallet_parsing`) and behaves identically for any `label:value` string.

- [ ] **Step 2: Add `ADA` to `COINGECKO_ID_MAP`**

In `KryptoWalletDashboard/backend/app/prices/coingecko.py`, add to `COINGECKO_ID_MAP`:
```python
    "ADA": "cardano",
```

- [ ] **Step 3: Write the failing tests for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_cardano_adapter_is_added_for_each_configured_address(monkeypatch):
    from app.adapters.cardano import CardanoAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(config, "CARDANO_WALLETS", [WalletConfig(label="main", address="addr1abc")])
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

    cardano_adapters = [a for a in adapters if isinstance(a, CardanoAdapter)]
    assert len(cardano_adapters) == 1
    assert cardano_adapters[0].account_label == "main"
    assert cardano_adapters[0].address == "addr1abc"


def test_cardano_stake_adapter_is_added_for_each_configured_stake_address(monkeypatch):
    from app.adapters.cardano import CardanoStakeAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(config, "CARDANO_WALLETS", [])
    monkeypatch.setattr(config, "CARDANO_STAKE_WALLETS", [WalletConfig(label="atomic", address="stake1abc")])
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

    stake_adapters = [a for a in adapters if isinstance(a, CardanoStakeAdapter)]
    assert len(stake_adapters) == 1
    assert stake_adapters[0].account_label == "atomic"
    assert stake_adapters[0].stake_address == "stake1abc"


def test_no_cardano_adapters_when_none_configured(monkeypatch):
    from app.adapters.cardano import CardanoAdapter, CardanoStakeAdapter

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

    assert not any(isinstance(a, (CardanoAdapter, CardanoStakeAdapter)) for a in adapters)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `build_adapters_from_config()` doesn't build any Cardano adapters yet.

- [ ] **Step 5: Wire both Cardano adapters into `app/adapters/factory.py`**

Add the import:
```python
from app.adapters.cardano import CardanoAdapter, CardanoStakeAdapter
```

Add these blocks, near the existing `config.SOLANA_WALLETS` loop:
```python
    for wallet in config.CARDANO_WALLETS:
        adapters.append(CardanoAdapter(account_label=wallet.label, address=wallet.address))

    for wallet in config.CARDANO_STAKE_WALLETS:
        adapters.append(CardanoStakeAdapter(account_label=wallet.label, stake_address=wallet.address))
```

- [ ] **Step 6: Run the new tests and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py tests/test_config.py -v`
Expected: PASS (all tests in both files, including the new ones).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/app/prices/coingecko.py KryptoWalletDashboard/backend/tests/test_config.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire both Cardano adapters into config and factory, add ADA to CoinGecko price map"
```

---

### Task 5: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document `CARDANO_ADDRESSES`/`CARDANO_STAKE_ADDRESSES` in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example`, after the existing Solana entry:
```
# Cardano: einzelne, feste Adressen (label:addr1...) - praktisch für z.B.
# eine einzelne Exchange-Einzahladresse.
CARDANO_ADDRESSES=main:addr1YourCardanoAddressHere...

# Cardano über die Stake-Adresse (empfohlen für ganze Wallets, z.B.
# AtomicWallet): erfasst automatisch ALLE Zahlungsadressen, die je zu
# dieser Stake-Adresse gehört haben - löst das Problem, dass Cardano-
# Wallets (wie Bitcoin) pro Transaktion neue Adressen generieren können,
# ohne dass wir das selbst nachbilden müssen.
CARDANO_STAKE_ADDRESSES=atomic:stake1YourStakeAddressHere...
```

- [ ] **Step 2: Document Cardano support and its limitations in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, after the existing Solana section:
```markdown
## Cardano

Native ADA- und Cardano-Native-Token-Transfers (CNTs) werden automatisch
erfasst, sobald `CARDANO_ADDRESSES` und/oder `CARDANO_STAKE_ADDRESSES`
gesetzt sind.

**Stake-Adresse (empfohlen) vs. einzelne Adresse:** wie Bitcoin können
Cardano-Wallets pro Transaktion neue Zahlungsadressen generieren - eine
einzelne fest eingetragene Adresse (`CARDANO_ADDRESSES`) kann daher
Transaktionen verpassen. `CARDANO_STAKE_ADDRESSES` (die Stake-Adresse
deines Wallets, beginnt mit `stake1...`, zu finden z.B. in AtomicWallet
unter den Cardano-Konto-Details) löst das eleganter als bei Bitcoin: die
verwendete Koios-API kennt bereits alle Zahlungsadressen, die je zu
dieser Stake-Adresse gehört haben, und liefert deren komplette
Transaktionshistorie direkt - keine eigene Adress-Ableitung nötig.

**Wichtig:** die Stake-Adresse macht deine gesamte Adress-/
Transaktionshistorie einsehbar für jeden, der sie kennt (sie erlaubt
aber keinerlei Zugriff auf deine Mittel) - trotzdem vertraulich
behandeln wie ein Passwort.

### Bekannte Einschränkung: Native Tokens ohne Symbol/CHF-Kurs/Dezimalstellen

Cardano-Native-Tokens (z.B. Stablecoins, NFT-nahe Assets) werden
vollständig erfasst (Menge, Zeitpunkt, Richtung), aber ohne lesbaren
Namen (nur Policy-ID + Asset-Name als roher Bezeichner), ohne CHF-Kurs,
und **ohne Dezimalstellen-Anpassung** (Cardano hat anders als bei
SPL-Tokens kein protokollseitiges Decimals-Feld - die Menge erscheint
als rohe Ganzzahl). Für die Steuererklärung muss der Bezeichner einmalig
manuell einem bekannten Token zugeordnet werden (z.B. über einen
Cardano-Explorer wie cardanoscan.io).
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document Cardano support, stake-address aggregation, and native-token limitations"
```

---

## Self-Review Notes

- **Spec coverage:** shared normalization with internal-transfer skip built in from the start (Task 1), Koios HTTP client + single-address adapter with mandatory live-API verification (Task 2), stake-address adapter reusing the same normalization (Task 3), config/factory wiring for both adapters plus the `COINGECKO_ID_MAP` ADA entry (Task 4), documentation covering both config paths and the native-token limitations (Task 5). Matches the design doc's scope exactly, including both confirmed user decisions (dual config paths, native tokens included).
- **Placeholder scan:** no TBD/TODO. The "API research caveat" (elevated to a *required* verification step in Task 2, not just a passive note) is a deliberate, explicit constraint reflecting genuinely higher uncertainty than prior phases' external-API research — not missing design work.
- **Type/signature consistency:** `normalize_cardano_tx(tx, owned_addresses: set[str], account_label, since)` (Task 1) is used identically by both `CardanoAdapter` (Task 2, `{self.address}`) and `CardanoStakeAdapter` (Task 3, the resolved multi-address set) — no divergent copies of the netting logic. `_fetch_tx_infos` (Task 2) is reused unchanged by `CardanoStakeAdapter` (Task 3). `CardanoAdapter.__init__(self, account_label, address)` and `CardanoStakeAdapter.__init__(self, account_label, stake_address)` (both fixed from their first commit) match exactly how `factory.py` constructs them (Task 4).
