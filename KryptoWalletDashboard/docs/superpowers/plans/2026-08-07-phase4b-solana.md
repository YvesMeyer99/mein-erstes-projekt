# Phase 4b – Solana Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `SolanaAdapter` that fetches native SOL and SPL-token transfers for one or more configured Solana addresses (e.g. multiple Ledger accounts), completing the Swiss crypto tax dashboard's chain coverage alongside Bitcoin and the 6 EVM chains.

**Architecture:** Solana's public JSON-RPC endpoint (`api.mainnet-beta.solana.com`) is queried via raw JSON-RPC POST requests (a new pattern for this codebase — every prior chain/exchange integration used REST-style GET/signed-GET APIs). `getSignaturesForAddress` lists a wallet's transaction signatures with `blockTime`/`err` already attached, letting `since`-filtering and failed-transaction filtering happen cheaply before the more expensive `getTransaction` call. `getTransaction`'s `meta.preBalances`/`postBalances` (native SOL, indexed to `accountKeys`) and `meta.preTokenBalances`/`postTokenBalances` (SPL tokens, matched by `owner`) give balance deltas directly — no on-chain instruction parsing needed. A single transaction can move both SOL and an SPL token (e.g. a DEX swap) — this adapter reports each as an independent `transfer_in`/`transfer_out` leg (no swap-pairing heuristic, matching the existing Bitcoin/EVM chain-adapter convention) with per-leg-unique `external_id`s.

**Tech Stack:** Same as Phase 1/2a (Python, `requests`, `responses` for test mocking, pytest). No new dependency — Solana's JSON-RPC needs only `requests.post` with a JSON body, unlike Bitcoin's xpub work which needed `bitcoinlib`.

**Related docs:**
- [`docs/superpowers/specs/2026-08-07-phase4b-solana-design.md`](../specs/2026-08-07-phase4b-solana-design.md)

**Scope notes (decided during design, confirmed with user):**
- **SPL tokens are included**, but reported with their raw mint address as `asset` (no symbol resolution, no CHF price) — a deliberate, accepted limitation mirroring the already-shipped ERC-20 "no CHF valuation" limitation. Resolving mint→symbol would need a new external token-list dependency, out of scope for this plan (confirmed with user).
- **No gap-limit/HD scanning needed, unlike Bitcoin.** Solana wallets (including Ledger) use fixed addresses per account, not a new address per transaction — multiple accounts just means multiple independent, fixed addresses in a comma-separated config list, identical in shape to `ETHEREUM_ADDRESSES`.
- **RPC endpoint is hardcoded**, not configurable (confirmed with user) — matches the existing precedent of Blockstream's URL being hardcoded for Bitcoin.
- **No swap-pairing.** A transaction that both decreases SOL and increases a token balance (e.g. a DEX swap) is reported as two independent legs, not merged into one `tx_type="swap"` entry — this is more honest than guessing "this looks like a swap" from raw balance diffs, and matches how the existing Bitcoin/EVM chain adapters already behave (only *exchange* adapters like Kraken/MEXC do explicit swap-pairing, because there the exchange's own ledger explicitly marks a trade as one unit).
- **No RPC retry/backoff for rate limits in this first version** — matches the already-accepted precedent of Bitcoin's Blockstream adapter having no retry logic, appropriate for a public endpoint used only via occasional manual sync. Can be added later as a small follow-up if it becomes a real problem in practice.
- **`COINGECKO_ID_MAP` needs a `"SOL": "solana"` entry** (Task 4) so native SOL gets CHF pricing through the existing `sync.py` pipeline — SPL tokens remain unpriced per the limitation above.
- **API research caveat:** Solana's RPC shapes were verified against `solana.com/docs/rpc` on 2026-08-07, but external APIs can drift — if shapes don't match reality by implementation time, treat the design's *intent* (JSON-RPC calls, signature-level pre-filtering, balance-delta-based normalization) as authoritative and adjust field names to match current docs, the same caveat pattern already used successfully in prior phases.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      solana.py               # NEW — SolanaAdapter (RPC client, native SOL + SPL token normalization)
      factory.py                  # MODIFIED — build SolanaAdapter per SOLANA_ADDRESSES entry
    config.py                      # MODIFIED — SOLANA_WALLETS (reuses existing parse_wallets)
    prices/
      coingecko.py                    # MODIFIED — add "SOL": "solana" to COINGECKO_ID_MAP
  .env.example                          # MODIFIED — document SOLANA_ADDRESSES
  README.md                              # MODIFIED — document Solana support and its SPL-token limitation
  tests/
    test_solana_adapter.py                  # NEW — all SolanaAdapter tests
    test_config.py                              # MODIFIED — SOLANA_WALLETS parsing
    test_factory.py                                # MODIFIED — factory wiring
```

---

### Task 1: Solana RPC Client & Signature Discovery

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/solana.py`
- Create: `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`

**Data source:** `https://api.mainnet-beta.solana.com`, JSON-RPC POST (`{"jsonrpc": "2.0", "id": 1, "method": ..., "params": [...]}`, response has a `result` key on success or an `error` key on failure). `getSignaturesForAddress(address, {limit, before})` returns signature entries newest-first with `signature`, `blockTime` (unix seconds, may be `null`), and `err` (an error object, or `null` on success) already attached — both `since`-filtering and failed-tx filtering can happen here, before the more expensive `getTransaction` call. Pagination: pass `before=<last signature of previous page>`, stop when a page has fewer than `limit` (1000) entries.

This task builds the RPC/pagination/filtering machinery with `_normalize_tx` stubbed to always return `[]` — Task 2 fills in native SOL normalization, Task 3 fills in SPL-token normalization. This mirrors the same stub-then-fill pattern already used successfully for the MEXC and Binance adapters in prior phases.

- [ ] **Step 1: Write the failing tests**

Create `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`:
```python
import json

import responses

from app.adapters.solana import SolanaAdapter

ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
API_URL = "https://api.mainnet-beta.solana.com"


def _rpc_result(result):
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def _sig(signature, block_time, err=None):
    return {
        "signature": signature,
        "slot": 1,
        "err": err,
        "blockTime": block_time,
        "memo": None,
        "confirmationStatus": "finalized",
    }


def _mock_rpc(result):
    responses.add(responses.POST, API_URL, json=_rpc_result(result), status=200)


def _rpc_calls():
    calls = []
    for call in responses.calls:
        body = json.loads(call.request.body)
        calls.append((body["method"], body["params"]))
    return calls


def _minimal_tx():
    return {
        "transaction": {"message": {"accountKeys": [ADDRESS]}},
        "meta": {
            "preBalances": [1000],
            "postBalances": [1000],
            "fee": 0,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


@responses.activate
def test_fetches_signatures_and_calls_gettransaction_for_each_surviving_candidate():
    _mock_rpc([_sig("sig1", 1700000000), _sig("sig2", 1700000100)])
    _mock_rpc(_minimal_tx())
    _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    methods = [m for m, _ in _rpc_calls()]
    assert methods == ["getSignaturesForAddress", "getTransaction", "getTransaction"]


@responses.activate
def test_failed_transactions_are_skipped_without_calling_gettransaction():
    _mock_rpc(
        [
            _sig("sig-ok", 1700000000),
            _sig("sig-failed", 1700000100, err={"InstructionError": [0, "Foo"]}),
        ]
    )
    _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    get_tx_calls = [c for c in _rpc_calls() if c[0] == "getTransaction"]
    assert len(get_tx_calls) == 1
    assert get_tx_calls[0][1][0] == "sig-ok"


@responses.activate
def test_signatures_without_block_time_are_skipped():
    _mock_rpc([_sig("sig-pending", None)])

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    assert [c[0] for c in _rpc_calls()] == ["getSignaturesForAddress"]


@responses.activate
def test_since_filters_out_older_signatures_before_fetching_transactions():
    from datetime import datetime, timezone

    _mock_rpc([_sig("sig-old", 1700000000), _sig("sig-new", 1700001000)])
    _mock_rpc(_minimal_tx())

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(since)

    get_tx_calls = [c for c in _rpc_calls() if c[0] == "getTransaction"]
    assert len(get_tx_calls) == 1
    assert get_tx_calls[0][1][0] == "sig-new"


@responses.activate
def test_paginates_through_signatures_until_short_page():
    full_page = [_sig(f"sig-{i}", 1700000000 + i) for i in range(1000)]
    short_page = [_sig("sig-last", 1700002000)]
    _mock_rpc(full_page)
    _mock_rpc(short_page)
    for _ in range(1001):
        _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    sig_calls = [c for c in _rpc_calls() if c[0] == "getSignaturesForAddress"]
    assert len(sig_calls) == 2
    assert sig_calls[1][1][1]["before"] == "sig-999"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.solana'`.

- [ ] **Step 3: Implement `app/adapters/solana.py`**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

API_URL = "https://api.mainnet-beta.solana.com"
LAMPORTS_PER_SOL = Decimal(10**9)
SIGNATURE_PAGE_LIMIT = 1000


class SolanaAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "solana"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def _rpc_call(self, method: str, params: list) -> dict:
        response = requests.post(
            API_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"Solana RPC error calling {method}: {body['error']}")
        return body["result"]

    def fetch_transactions(self, since) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for entry in self._fetch_candidate_signatures(since):
            tx = self._rpc_call(
                "getTransaction",
                [entry["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}],
            )
            if tx is None:
                continue
            timestamp = datetime.fromtimestamp(entry["blockTime"], tz=timezone.utc)
            results.extend(self._normalize_tx(tx, entry["signature"], timestamp))
        return results

    def _fetch_candidate_signatures(self, since) -> list[dict]:
        """Paginate getSignaturesForAddress, filtering out failed and
        too-old entries before the caller ever calls getTransaction."""
        candidates: list[dict] = []
        before = None
        while True:
            params_opts = {"limit": SIGNATURE_PAGE_LIMIT}
            if before is not None:
                params_opts["before"] = before
            page = self._rpc_call("getSignaturesForAddress", [self.address, params_opts])
            for entry in page:
                if entry.get("err") is not None:
                    continue
                if entry.get("blockTime") is None:
                    continue
                timestamp = datetime.fromtimestamp(entry["blockTime"], tz=timezone.utc)
                if since is not None and timestamp <= since:
                    continue
                candidates.append(entry)
            if len(page) < SIGNATURE_PAGE_LIMIT:
                break
            before = page[-1]["signature"]
        return candidates

    def _normalize_tx(self, tx: dict, signature: str, timestamp) -> list[NormalizedTransaction]:
        # Task 2 and Task 3 fill this in (native SOL leg, SPL token legs).
        return []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/solana.py KryptoWalletDashboard/backend/tests/test_solana_adapter.py
git commit -m "feat: Solana JSON-RPC client with signature discovery and pre-filtering"
```

---

### Task 2: Native SOL Transfer Normalization

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/solana.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`

**Data source:** `getTransaction`'s `meta.preBalances`/`meta.postBalances` (lamports, indexed to `transaction.message.accountKeys`) and `meta.fee` (lamports, paid by `accountKeys[0]`, the fee payer).

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`:
```python
from decimal import Decimal

OTHER = "11111111111111111111111111111111111111111"


def _tx(account_keys, pre_balances, post_balances, fee=5000):
    return {
        "transaction": {"message": {"accountKeys": account_keys}},
        "meta": {
            "preBalances": pre_balances,
            "postBalances": post_balances,
            "fee": fee,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


@responses.activate
def test_incoming_sol_transfer_is_transfer_in():
    _mock_rpc([_sig("sig-in", 1700000000)])
    _mock_rpc(
        _tx([OTHER, ADDRESS], pre_balances=[2000000000, 1000000000], post_balances=[1000000000, 2000000000])
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "SOL"
    assert tx.amount == Decimal("1000000000") / Decimal(10**9)
    assert tx.fee_amount is None
    assert tx.external_id == "sig-in-native"


@responses.activate
def test_outgoing_sol_transfer_as_fee_payer_includes_fee():
    _mock_rpc([_sig("sig-out", 1700000100)])
    # ADDRESS is accountKeys[0] -> the fee payer. Sent 0.5 SOL, paid a
    # 5000-lamport fee; both are already reflected in the balance delta.
    _mock_rpc(
        _tx(
            [ADDRESS, OTHER],
            pre_balances=[2000000000, 0],
            post_balances=[1499995000, 500000000],
            fee=5000,
        )
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("500005000") / Decimal(10**9)
    assert tx.fee_amount == Decimal("5000") / Decimal(10**9)
    assert tx.fee_asset == "SOL"


@responses.activate
def test_outgoing_transfer_not_as_fee_payer_has_no_fee_attributed():
    _mock_rpc([_sig("sig-out2", 1700000200)])
    # ADDRESS is accountKeys[1], NOT the fee payer.
    _mock_rpc(
        _tx(
            [OTHER, ADDRESS],
            pre_balances=[2000000000, 1000000000],
            post_balances=[1000000000, 500000000],
            fee=5000,
        )
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("500000000") / Decimal(10**9)
    assert tx.fee_amount is None


@responses.activate
def test_zero_net_change_produces_no_native_entry():
    _mock_rpc([_sig("sig-noop", 1700000300)])
    _mock_rpc(_tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0]))

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_address_not_present_in_account_keys_produces_no_entry():
    _mock_rpc([_sig("sig-weird", 1700000400)])
    _mock_rpc(_tx([OTHER], pre_balances=[1000000000], post_balances=[900000000]))

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: FAIL — the 5 new tests fail (`_normalize_tx` still returns `[]` unconditionally).

- [ ] **Step 3: Implement native SOL normalization**

Replace the stub `_normalize_tx` in `app/adapters/solana.py` with:
```python
    def _normalize_tx(self, tx: dict, signature: str, timestamp) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []

        account_keys = tx["transaction"]["message"]["accountKeys"]
        if self.address in account_keys:
            idx = account_keys.index(self.address)
            net_lamports = tx["meta"]["postBalances"][idx] - tx["meta"]["preBalances"][idx]
            if net_lamports != 0:
                fee_amount = None
                fee_asset = None
                if idx == 0 and net_lamports < 0:
                    fee_amount = Decimal(tx["meta"]["fee"]) / LAMPORTS_PER_SOL
                    fee_asset = "SOL"
                results.append(
                    NormalizedTransaction(
                        timestamp=timestamp,
                        source_type=self.source_type,
                        source_name=self.source_name,
                        account_label=self.account_label,
                        tx_type="transfer_in" if net_lamports > 0 else "transfer_out",
                        asset="SOL",
                        amount=Decimal(abs(net_lamports)) / LAMPORTS_PER_SOL,
                        fee_amount=fee_amount,
                        fee_asset=fee_asset,
                        external_id=f"{signature}-native",
                        raw_json=json.dumps(tx),
                    )
                )

        return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: PASS (10 tests: 5 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/solana.py KryptoWalletDashboard/backend/tests/test_solana_adapter.py
git commit -m "feat: native SOL transfer normalization"
```

---

### Task 3: SPL Token Transfer Normalization

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/solana.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`

**Data source:** `meta.preTokenBalances`/`meta.postTokenBalances`, each entry keyed by `accountIndex` with `mint`, `owner`, and `uiTokenAmount.{amount, decimals}` (raw integer string + decimal places). Matched between pre/post by `accountIndex`; an index present in only one of the two lists means the token account was created or fully emptied in this transaction (treat the missing side as zero balance).

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_solana_adapter.py`:
```python
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@responses.activate
def test_incoming_spl_token_transfer_is_transfer_in():
    _mock_rpc([_sig("sig-token-in", 1700000500)])
    tx = _tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0])
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 2, "mint": USDC_MINT, "owner": ADDRESS, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 2, "mint": USDC_MINT, "owner": ADDRESS, "uiTokenAmount": {"amount": "1500000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == USDC_MINT
    assert r.amount == Decimal("500000") / Decimal(10**6)
    assert r.external_id == f"sig-token-in-{USDC_MINT}"


@responses.activate
def test_newly_created_token_account_with_no_prior_balance_counts_as_transfer_in():
    _mock_rpc([_sig("sig-new-account", 1700000600)])
    tx = _tx([ADDRESS], pre_balances=[1000000000], post_balances=[997000000])  # rent for new token account
    tx["meta"]["preTokenBalances"] = []
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 1, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": ADDRESS, "uiTokenAmount": {"amount": "5000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    token_results = [r for r in results if r.asset != "SOL"]
    assert len(token_results) == 1
    assert token_results[0].tx_type == "transfer_in"
    assert token_results[0].amount == Decimal("5000000") / Decimal(10**6)


@responses.activate
def test_token_balance_for_a_different_owner_is_ignored():
    _mock_rpc([_sig("sig-other-owner", 1700000700)])
    tx = _tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0])
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 2, "mint": "SomeMint111111111111111111111111111111111", "owner": OTHER, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 2, "mint": "SomeMint111111111111111111111111111111111", "owner": OTHER, "uiTokenAmount": {"amount": "2000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_swap_produces_both_a_sol_leg_and_a_token_leg_with_distinct_external_ids():
    _mock_rpc([_sig("sig-swap", 1700000800)])
    token_mint = "TokenMint1111111111111111111111111111111"
    tx = _tx([ADDRESS, OTHER], pre_balances=[2000000000, 0], post_balances=[1000000000, 0], fee=5000)
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 1, "mint": token_mint, "owner": ADDRESS, "uiTokenAmount": {"amount": "0", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 1, "mint": token_mint, "owner": ADDRESS, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 2
    external_ids = {r.external_id for r in results}
    assert external_ids == {"sig-swap-native", f"sig-swap-{token_mint}"}
    sol_leg = next(r for r in results if r.asset == "SOL")
    token_leg = next(r for r in results if r.asset != "SOL")
    assert sol_leg.tx_type == "transfer_out"
    assert token_leg.tx_type == "transfer_in"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: FAIL — the 4 new tests fail (no token-leg logic exists yet).

- [ ] **Step 3: Implement SPL token normalization**

Modify `_normalize_tx` in `app/adapters/solana.py` to also call a new `_normalize_token_legs` method, appending its results:
```python
    def _normalize_tx(self, tx: dict, signature: str, timestamp) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []

        account_keys = tx["transaction"]["message"]["accountKeys"]
        if self.address in account_keys:
            idx = account_keys.index(self.address)
            net_lamports = tx["meta"]["postBalances"][idx] - tx["meta"]["preBalances"][idx]
            if net_lamports != 0:
                fee_amount = None
                fee_asset = None
                if idx == 0 and net_lamports < 0:
                    fee_amount = Decimal(tx["meta"]["fee"]) / LAMPORTS_PER_SOL
                    fee_asset = "SOL"
                results.append(
                    NormalizedTransaction(
                        timestamp=timestamp,
                        source_type=self.source_type,
                        source_name=self.source_name,
                        account_label=self.account_label,
                        tx_type="transfer_in" if net_lamports > 0 else "transfer_out",
                        asset="SOL",
                        amount=Decimal(abs(net_lamports)) / LAMPORTS_PER_SOL,
                        fee_amount=fee_amount,
                        fee_asset=fee_asset,
                        external_id=f"{signature}-native",
                        raw_json=json.dumps(tx),
                    )
                )

        results.extend(self._normalize_token_legs(tx, signature, timestamp))
        return results

    def _normalize_token_legs(self, tx: dict, signature: str, timestamp) -> list[NormalizedTransaction]:
        pre_by_index = {b["accountIndex"]: b for b in tx["meta"].get("preTokenBalances", [])}
        post_by_index = {b["accountIndex"]: b for b in tx["meta"].get("postTokenBalances", [])}

        results: list[NormalizedTransaction] = []
        for idx in sorted(set(pre_by_index) | set(post_by_index)):
            pre_entry = pre_by_index.get(idx)
            post_entry = post_by_index.get(idx)
            reference = post_entry or pre_entry
            if reference.get("owner") != self.address:
                continue

            mint = reference["mint"]
            decimals = reference["uiTokenAmount"]["decimals"]
            pre_amount = Decimal(pre_entry["uiTokenAmount"]["amount"]) if pre_entry else Decimal(0)
            post_amount = Decimal(post_entry["uiTokenAmount"]["amount"]) if post_entry else Decimal(0)
            net = post_amount - pre_amount
            if net == 0:
                continue

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in" if net > 0 else "transfer_out",
                    asset=mint,
                    amount=abs(net) / Decimal(10**decimals),
                    external_id=f"{signature}-{mint}",
                    raw_json=json.dumps(tx),
                )
            )
        return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_solana_adapter.py -v`
Expected: PASS (14 tests: 10 from Task 2 + 4 new).

Run the full suite: `.venv/Scripts/pytest -v`
Expected: PASS, all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/solana.py KryptoWalletDashboard/backend/tests/test_solana_adapter.py
git commit -m "feat: SPL token transfer normalization"
```

---

### Task 4: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/app/prices/coingecko.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Write the failing test for `SOLANA_WALLETS` parsing**

Append to `KryptoWalletDashboard/backend/tests/test_config.py`:
```python
def test_solana_wallets_reuses_wallet_parsing():
    from app.config import parse_wallets

    result = parse_wallets("ledger-1:9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM,ledger-2:11111111111111111111111111111111111111111")

    assert len(result) == 2
    assert result[0].label == "ledger-1"
    assert result[1].label == "ledger-2"
```

This confirms `parse_wallets()` (already used for `BITCOIN_ADDRESSES`/`ETHEREUM_ADDRESSES`/`BITCOIN_XPUBS`) works unmodified for Solana addresses too — no new parsing function needed.

- [ ] **Step 2: Run the test to verify it passes immediately (characterization test)**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS immediately — `parse_wallets` already handles this input correctly.

- [ ] **Step 3: Add the `SOLANA_WALLETS` module constant to `app/config.py`**

Add alongside the existing `ETHEREUM_WALLETS` constant in `KryptoWalletDashboard/backend/app/config.py`:
```python
SOLANA_WALLETS = parse_wallets(os.getenv("SOLANA_ADDRESSES"))
```

- [ ] **Step 4: Add `SOL` to `COINGECKO_ID_MAP`**

In `KryptoWalletDashboard/backend/app/prices/coingecko.py`, add to the existing `COINGECKO_ID_MAP` dict:
```python
    "SOL": "solana",
```

- [ ] **Step 5: Write the failing test for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_solana_adapter_is_added_for_each_configured_address(monkeypatch):
    from app.adapters.solana import SolanaAdapter
    from app.config import WalletConfig

    monkeypatch.setattr(
        config,
        "SOLANA_WALLETS",
        [WalletConfig(label="ledger-1", address="9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM")],
    )
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

    solana_adapters = [a for a in adapters if isinstance(a, SolanaAdapter)]
    assert len(solana_adapters) == 1
    assert solana_adapters[0].account_label == "ledger-1"
    assert solana_adapters[0].address == "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


def test_no_solana_adapters_when_none_configured(monkeypatch):
    from app.adapters.solana import SolanaAdapter

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

    assert not any(isinstance(a, SolanaAdapter) for a in adapters)
```

Check `app/adapters/factory.py`'s existing tests for whether `BITCOIN_XPUBS` also needs neutralizing in the *other*, pre-existing factory tests (it was added in the prior phase) — if any existing test in `test_factory.py` doesn't already neutralize `config.BITCOIN_XPUBS`/`config.SOLANA_WALLETS` and now fails because a stray adapter appears, add the missing `monkeypatch.setattr` line to that existing test rather than leaving it broken.

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `build_adapters_from_config()` doesn't build any `SolanaAdapter` yet.

- [ ] **Step 7: Wire `SolanaAdapter` into `app/adapters/factory.py`**

Add the import:
```python
from app.adapters.solana import SolanaAdapter
```

Add this block, near the existing loop that builds one adapter per `config.ETHEREUM_WALLETS`/`config.BITCOIN_XPUBS` entry (read the existing file first to match its exact loop style and choose a sensible position, e.g. after the Bitcoin-related blocks):
```python
    for wallet in config.SOLANA_WALLETS:
        adapters.append(SolanaAdapter(account_label=wallet.label, address=wallet.address))
```

- [ ] **Step 8: Run the new tests and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py tests/test_config.py -v`
Expected: PASS (all tests in both files, including the new ones).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 9: Commit**

```bash
git add KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/app/prices/coingecko.py KryptoWalletDashboard/backend/tests/test_config.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire SolanaAdapter into config and factory, add SOL to CoinGecko price map"
```

---

### Task 5: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document `SOLANA_ADDRESSES` in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example`, after the existing Bitcoin-related entries (`BITCOIN_ADDRESSES`/`BITCOIN_XPUBS`):
```
# Solana: comma-separated label:address pairs. Unlike Bitcoin, Solana
# wallets (including Ledger) use one fixed address per account - no HD
# address rotation - so multiple accounts just means multiple entries
# here, same format as ETHEREUM_ADDRESSES.
SOLANA_ADDRESSES=ledger-1:YourSolanaAddressHere...,ledger-2:AnotherAddress...
```

- [ ] **Step 2: Document Solana support and its SPL-token limitation in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, after the existing Bitcoin xpub section:
```markdown
## Solana

Native SOL- und SPL-Token-Transfers werden automatisch erfasst, sobald
`SOLANA_ADDRESSES` gesetzt ist. Anders als bei Bitcoin generieren
Solana-Wallets (auch Ledger) keine neue Adresse pro Transaktion - jeder
Account hat eine feste Adresse. Für mehrere Accounts (z.B. mehrere
Ledger-Konten) einfach mehrere `label:adresse`-Paare komma-getrennt
eintragen, wie bei `ETHEREUM_ADDRESSES`.

### Bekannte Einschränkung: SPL-Tokens ohne Symbol/CHF-Kurs

SPL-Token-Transfers (z.B. USDC auf Solana) werden vollständig erfasst
(Menge, Zeitpunkt, Richtung), aber die Solana-API liefert kein
Token-Symbol - nur die Mint-Adresse. Im CSV-Export erscheint daher die
rohe Mint-Adresse statt eines lesbaren Namens wie "USDC", und ohne
CHF-Kurs (analog zur bestehenden Einschränkung bei ERC-20-Tokens). Für
die Steuererklärung muss die Mint-Adresse einmalig manuell einem
bekannten Token zugeordnet werden (z.B. über einen Solana-Explorer wie
solscan.io).
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document Solana support and the SPL-token symbol/pricing limitation"
```

---

## Self-Review Notes

- **Spec coverage:** RPC client + signature pre-filtering (Task 1), native SOL normalization with correct fee-payer-only fee attribution (Task 2), SPL token normalization with per-leg-unique external_ids and owner-matching (Task 3), config/factory wiring plus the `COINGECKO_ID_MAP` SOL entry (Task 4), documentation including the SPL-token limitation (Task 5). Matches the design doc's scope exactly.
- **Placeholder scan:** no TBD/TODO. The "API research caveat" is a deliberate, explicit constraint (matching the pattern already used successfully in every prior phase's plan), not missing design work.
- **Type/signature consistency:** `SolanaAdapter.__init__(self, account_label, address)` (Task 1) is unchanged through Tasks 2-3 and matches exactly how `factory.py` constructs it (Task 4). `_normalize_tx(tx, signature, timestamp)` (Task 1's stub) keeps the same signature through Tasks 2-3's real implementations. `_normalize_token_legs(tx, signature, timestamp)` (Task 3) is a new private method, not referenced anywhere before Task 3 introduces it. `parse_wallets`/`WalletConfig` (reused, not modified) match the exact pattern already established for `BITCOIN_WALLETS`/`ETHEREUM_WALLETS`/`BITCOIN_XPUBS`.
