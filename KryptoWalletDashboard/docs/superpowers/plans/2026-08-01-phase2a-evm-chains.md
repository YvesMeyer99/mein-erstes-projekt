# Phase 2a – Weitere EVM-Chains Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the Phase 1 `EthereumAdapter` into a parametrized `EvmAdapter` that covers all six EVM chains (Ethereum, Polygon, BSC, Arbitrum, Optimism, Base) via Etherscan's V2 multi-chain API, including native-coin and ERC-20-token transfers, wired into the sync pipeline through one shared wallet-address list.

**Architecture:** One `EvmAdapter` class parametrized by `chain_id`/`chain_name`/`native_asset`, reusing the existing `page`/`offset` pagination pattern from Phase 1. A small static chain registry drives `factory.build_adapters_from_config()` to build six adapter instances per configured Ethereum wallet address (no new `.env` variables). Token transfers are fetched via a second Etherscan action (`tokentx`) and normalized using the symbol/decimals Etherscan already returns per transfer.

**Tech Stack:** Same as Phase 1 — Python, `requests`, `responses` for test mocking, pytest. No new dependencies.

**Related docs:**
- [`docs/superpowers/specs/2026-08-01-phase2-evm-chains-design.md`](../specs/2026-08-01-phase2-evm-chains-design.md)
- [`docs/superpowers/plans/2026-07-30-backend-phase1.md`](2026-07-30-backend-phase1.md) (Phase 1, already merged/mergeable — this plan builds directly on top of it)

**Scope notes (decided during planning):**
- This plan covers **EVM chains only**. Binance/Coinbase/MEXC are a separate follow-up plan (2b), as agreed in the design.
- **Ethereum itself is migrated** to the new `EvmAdapter` (as `chain_id=1`) rather than kept as a separate class — this avoids two near-identical code paths for the same API family. `app/adapters/ethereum.py` and `tests/test_ethereum_adapter.py` are deleted; their logic and tests move into `app/adapters/evm.py`/`tests/test_evm_adapter.py`.
- **No fiat/exchange-side changes.** Only `app/adapters/`, `app/adapters/factory.py`, `app/prices/coingecko.py`, and the README are touched. `app/sync.py`, `app/portfolio.py`, `app/csv_export.py`, `app/main.py` need **no changes** — they already operate generically on whatever adapters `factory.build_adapters_from_config()` returns.
- **Known, accepted simplification for combined native+token transactions:** if a single on-chain transaction both moves native value AND transfers an ERC-20 token (e.g. some DEX router calls), the gas fee will be reported on BOTH the native leg and the token leg (double-counted). This is rare for simple wallet activity (a plain ERC-20 `transfer()` call has `value=0` and therefore contributes no native leg at all — see Task 2), and fixing it would require cross-referencing `txlist` and `tokentx` by hash, which is out of scope for this plan. Documented here so a future reader doesn't mistake it for an oversight.
- **Native-asset pricing:** `BNB` and `MATIC` need CoinGecko price mappings (Task 4). No new entries are needed in `app/assets.py`'s canonical-symbol map — nothing in this plan produces an alternate spelling of an existing asset the way Kraken's `XBT`/`ETH2` did in Phase 1.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      ethereum.py        # DELETED (Task 1)
      evm.py              # NEW — EvmAdapter (native + token transfers)
      evm_chains.py        # NEW — static chain registry (chain_id/name/native_asset)
      factory.py            # MODIFIED — build 6 EvmAdapter instances per wallet
    prices/
      coingecko.py            # MODIFIED — add BNB/MATIC to COINGECKO_ID_MAP
    README.md                  # MODIFIED — document the 6 supported EVM chains
  tests/
    test_ethereum_adapter.py  # DELETED (Task 1)
    test_evm_adapter.py        # NEW — native-coin tests (migrated) + multi-chain param test
    test_evm_chains.py          # NEW — chain registry test
```

---

### Task 1: `EvmAdapter` — Native Coin Transfers (migrate + generalize)

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/evm.py`
- Create: `KryptoWalletDashboard/backend/tests/test_evm_adapter.py`
- Delete: `KryptoWalletDashboard/backend/app/adapters/ethereum.py`
- Delete: `KryptoWalletDashboard/backend/tests/test_ethereum_adapter.py`

**Data source:** Etherscan's V2 multi-chain API, `https://api.etherscan.io/v2/api`. Identical request shape to Phase 1's Etherscan V1 usage, plus one extra query param: `chainid`. `module=account&action=txlist` for native transfers, unchanged field shapes (`hash`, `timeStamp`, `from`, `to`, `value`, `gasUsed`, `gasPrice`, `isError`).

- [ ] **Step 1: Write the failing tests (migrated from `test_ethereum_adapter.py`, plus a new multi-chain test)**

`KryptoWalletDashboard/backend/tests/test_evm_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.evm import EvmAdapter

ADDRESS = "0xExampleAddress"
API_URL = "https://api.etherscan.io/v2/api"


def _tx(tx_hash, timestamp, from_addr, to_addr, value_wei, is_error="0", gas_used="21000", gas_price="20000000000"):
    return {
        "hash": tx_hash,
        "timeStamp": str(timestamp),
        "from": from_addr,
        "to": to_addr,
        "value": str(value_wei),
        "gasUsed": gas_used,
        "gasPrice": gas_price,
        "isError": is_error,
    }


def _ethereum_adapter():
    return EvmAdapter(
        account_label="main",
        address=ADDRESS,
        api_key="key",
        chain_id=1,
        chain_name="ethereum",
        native_asset="ETH",
    )


@responses.activate
def test_incoming_transaction_is_transfer_in():
    tx = _tx("0xin", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.source_name == "ethereum"
    assert result.tx_type == "transfer_in"
    assert result.asset == "ETH"
    assert result.amount == Decimal("1")
    assert result.fee_amount is None


@responses.activate
def test_outgoing_transaction_is_transfer_out_with_gas_fee():
    tx = _tx("0xout", 1700000100, ADDRESS, "0xSomeoneElse", 2 * 10**18)
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_out"
    assert result.amount == Decimal("2")
    assert result.fee_amount == (Decimal("21000") * Decimal("20000000000")) / Decimal(10**18)
    assert result.fee_asset == "ETH"


@responses.activate
def test_failed_transaction_is_skipped():
    tx = _tx("0xfailed", 1700000200, ADDRESS, "0xSomeoneElse", 10**18, is_error="1")
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = _ethereum_adapter()
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_transactions():
    older = _tx("0xold", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    newer = _tx("0xnew", 1700001000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [older, newer]},
        status=200,
    )

    adapter = _ethereum_adapter()
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["0xnew"]


@responses.activate
def test_no_transactions_found_does_not_raise():
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "0", "message": "No transactions found", "result": []},
        status=200,
    )

    adapter = _ethereum_adapter()
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_paginates_through_txlist_until_short_page():
    page1 = [
        _tx(f"0xpage1-{i}", 1700000000 + i, "0xSomeoneElse", ADDRESS, 10**18)
        for i in range(EvmAdapter.PAGE_SIZE)
    ]
    page2 = [_tx("0xpage2-0", 1700100000, "0xSomeoneElse", ADDRESS, 10**18)]

    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": page1},
        status=200,
    )
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": page2},
        status=200,
    )

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == EvmAdapter.PAGE_SIZE + 1
    assert {r.external_id for r in results} == {t["hash"] for t in page1} | {
        t["hash"] for t in page2
    }
    assert len(responses.calls) == 2
    assert "page=1" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url
    assert f"offset={EvmAdapter.PAGE_SIZE}" in responses.calls[0].request.url


@responses.activate
def test_chain_id_and_native_asset_are_parametrized_per_instance():
    """A second chain (Polygon) must use a different chainid param, source_name,
    and native asset symbol than Ethereum, using the exact same adapter class."""
    tx = _tx("0xpolygon-in", 1700000000, "0xSomeoneElse", ADDRESS, 5 * 10**18)
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EvmAdapter(
        account_label="main",
        address=ADDRESS,
        api_key="key",
        chain_id=137,
        chain_name="polygon",
        native_asset="MATIC",
    )
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    assert results[0].source_name == "polygon"
    assert results[0].asset == "MATIC"
    assert results[0].amount == Decimal("5")
    assert "chainid=137" in responses.calls[0].request.url
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_evm_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.evm'`.

- [ ] **Step 3: Implement `app/adapters/evm.py`**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

WEI_PER_NATIVE_UNIT = Decimal(10**18)


class EvmAdapter(TransactionAdapter):
    """Fetches native-coin transfers for one EVM-compatible chain via
    Etherscan's V2 multi-chain API. One instance = one (wallet, chain) pair;
    the same `api_key` works across every chain Etherscan V2 supports, only
    `chain_id` changes."""

    source_type = "chain"
    API_URL = "https://api.etherscan.io/v2/api"
    PAGE_SIZE = 1000

    def __init__(
        self,
        account_label: str,
        address: str,
        api_key: str,
        chain_id: int,
        chain_name: str,
        native_asset: str,
    ):
        super().__init__(account_label)
        self.address = address
        self.api_key = api_key
        self.chain_id = chain_id
        self.source_name = chain_name
        self.native_asset = native_asset

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        return self._native_transactions(since)

    def _native_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        address_lower = self.address.lower()
        results: list[NormalizedTransaction] = []
        for tx in self._fetch_all_pages("txlist"):
            if tx.get("isError") == "1":
                continue
            timestamp = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            value = Decimal(tx["value"]) / WEI_PER_NATIVE_UNIT
            if value == 0:
                continue

            is_outgoing = tx["from"].lower() == address_lower
            fee_amount = None
            fee_asset = None
            if is_outgoing:
                fee_amount = (Decimal(tx["gasUsed"]) * Decimal(tx["gasPrice"])) / WEI_PER_NATIVE_UNIT
                fee_asset = self.native_asset

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out" if is_outgoing else "transfer_in",
                    asset=self.native_asset,
                    amount=value,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["hash"],
                    raw_json=json.dumps(tx),
                )
            )
        return results

    def _fetch_all_pages(self, action: str) -> list[dict]:
        """Walk Etherscan's page/offset-paginated endpoint for the given action.

        Same termination rule as Phase 1's Bitcoin/Ethereum adapters: keep
        requesting subsequent pages, incrementing `page`, until a page comes
        back with fewer than PAGE_SIZE records - that short page signals
        there is nothing left to fetch. Etherscan also caps total records
        reachable via a single startblock/endblock window at 10'000 per
        chain; walking further would require chunking the block range,
        which is out of scope here.
        """
        all_items: list[dict] = []
        page = 1
        while True:
            params = {
                "chainid": self.chain_id,
                "module": "account",
                "action": action,
                "address": self.address,
                "startblock": 0,
                "endblock": 99999999,
                "page": page,
                "offset": self.PAGE_SIZE,
                "sort": "asc",
                "apikey": self.api_key,
            }
            response = requests.get(self.API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1" and data.get("message") != "No transactions found":
                raise RuntimeError(f"Etherscan-Fehler ({self.source_name}): {data.get('message')}")

            batch = data.get("result", [])
            all_items.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break
            page += 1

        return all_items
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_evm_adapter.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Delete the old Ethereum-specific adapter and its test**

```bash
git rm KryptoWalletDashboard/backend/app/adapters/ethereum.py
git rm KryptoWalletDashboard/backend/tests/test_ethereum_adapter.py
```

- [ ] **Step 6: Run the full suite to confirm nothing else references the deleted module**

Run: `.venv/Scripts/pytest -v`
Expected: PASS. (`app/adapters/factory.py` still imports `EthereumAdapter` at this point and will fail to import — this is expected and fixed in Task 3. If the full-suite run fails only on `test_api.py`/other files due to `factory.py`'s now-broken import, that's fine to leave broken until Task 3; do NOT fix `factory.py` in this task, keep this task's diff scoped to the adapter itself.)

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/evm.py KryptoWalletDashboard/backend/tests/test_evm_adapter.py
git commit -m "feat: generalize Ethereum adapter into parametrized multi-chain EvmAdapter"
```

---

### Task 2: ERC-20 Token Transfers

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/evm.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_evm_adapter.py`

**Data source:** Etherscan V2, `module=account&action=tokentx`, same base URL/pagination/chainid pattern as `txlist`. Each result item additionally has `tokenSymbol`, `tokenDecimal`, `contractAddress` (and still has `gasUsed`/`gasPrice`, since gas for a token-transfer transaction is paid in the chain's native asset).

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_evm_adapter.py`:
```python
def _token_tx(tx_hash, timestamp, from_addr, to_addr, value, token_symbol, token_decimal, contract_address, gas_used="65000", gas_price="20000000000"):
    return {
        "hash": tx_hash,
        "timeStamp": str(timestamp),
        "from": from_addr,
        "to": to_addr,
        "value": str(value),
        "tokenSymbol": token_symbol,
        "tokenDecimal": str(token_decimal),
        "contractAddress": contract_address,
        "gasUsed": gas_used,
        "gasPrice": gas_price,
    }


@responses.activate
def test_incoming_token_transfer_is_transfer_in():
    native_page = {"status": "0", "message": "No transactions found", "result": []}
    token = _token_tx(
        "0xtoken-in", 1700000000, "0xSomeoneElse", ADDRESS,
        value=5_000_000, token_symbol="USDC", token_decimal=6,
        contract_address="0xusdccontract",
    )
    token_page = {"status": "1", "message": "OK", "result": [token]}
    responses.add(responses.GET, API_URL, json=native_page, status=200)
    responses.add(responses.GET, API_URL, json=token_page, status=200)

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_in"
    assert result.asset == "USDC"
    assert result.amount == Decimal("5")
    assert result.fee_amount is None
    assert result.external_id == "0xtoken-in-token-0xusdccontract"


@responses.activate
def test_outgoing_token_transfer_has_native_gas_fee():
    native_page = {"status": "0", "message": "No transactions found", "result": []}
    token = _token_tx(
        "0xtoken-out", 1700000100, ADDRESS, "0xSomeoneElse",
        value=10_000_000, token_symbol="USDT", token_decimal=6,
        contract_address="0xusdtcontract",
    )
    token_page = {"status": "1", "message": "OK", "result": [token]}
    responses.add(responses.GET, API_URL, json=native_page, status=200)
    responses.add(responses.GET, API_URL, json=token_page, status=200)

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_out"
    assert result.asset == "USDT"
    assert result.amount == Decimal("10")
    assert result.fee_amount == (Decimal("65000") * Decimal("20000000000")) / Decimal(10**18)
    assert result.fee_asset == "ETH"


@responses.activate
def test_token_transfer_since_filter_is_applied():
    native_page = {"status": "0", "message": "No transactions found", "result": []}
    older = _token_tx("0xold", 1700000000, "0xSomeoneElse", ADDRESS, 1_000_000, "USDC", 6, "0xc")
    newer = _token_tx("0xnew", 1700001000, "0xSomeoneElse", ADDRESS, 1_000_000, "USDC", 6, "0xc")
    token_page = {"status": "1", "message": "OK", "result": [older, newer]}
    responses.add(responses.GET, API_URL, json=native_page, status=200)
    responses.add(responses.GET, API_URL, json=token_page, status=200)

    adapter = _ethereum_adapter()
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["0xnew-token-0xc"]


@responses.activate
def test_native_and_token_transfers_are_both_returned_together():
    native_tx = _tx("0xnative", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    native_page = {"status": "1", "message": "OK", "result": [native_tx]}
    token = _token_tx("0xtoken", 1700000100, "0xSomeoneElse", ADDRESS, 1_000_000, "USDC", 6, "0xc")
    token_page = {"status": "1", "message": "OK", "result": [token]}
    responses.add(responses.GET, API_URL, json=native_page, status=200)
    responses.add(responses.GET, API_URL, json=token_page, status=200)

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assets = {r.asset for r in results}
    assert assets == {"ETH", "USDC"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_evm_adapter.py -v`
Expected: FAIL — `test_incoming_token_transfer_is_transfer_in` and friends fail because `fetch_transactions` doesn't fetch `tokentx` yet (assertions about `USDC`/`USDT` results won't match; results will be empty or wrong length).

- [ ] **Step 3: Implement token-transfer support in `app/adapters/evm.py`**

Modify `fetch_transactions` and add `_token_transactions`:
```python
    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results = self._native_transactions(since)
        results.extend(self._token_transactions(since))
        return results
```

Add after `_native_transactions`:
```python
    def _token_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        address_lower = self.address.lower()
        results: list[NormalizedTransaction] = []
        for tx in self._fetch_all_pages("tokentx"):
            timestamp = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            decimals = int(tx["tokenDecimal"])
            amount = Decimal(tx["value"]) / Decimal(10**decimals)
            if amount == 0:
                continue

            is_outgoing = tx["from"].lower() == address_lower
            fee_amount = None
            fee_asset = None
            if is_outgoing:
                fee_amount = (Decimal(tx["gasUsed"]) * Decimal(tx["gasPrice"])) / WEI_PER_NATIVE_UNIT
                fee_asset = self.native_asset

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out" if is_outgoing else "transfer_in",
                    asset=tx["tokenSymbol"],
                    amount=amount,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=f"{tx['hash']}-token-{tx['contractAddress']}",
                    raw_json=json.dumps(tx),
                )
            )
        return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_evm_adapter.py -v`
Expected: PASS (11 tests: 7 from Task 1 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/evm.py KryptoWalletDashboard/backend/tests/test_evm_adapter.py
git commit -m "feat: fetch ERC-20 token transfers via Etherscan tokentx"
```

---

### Task 3: EVM Chain Registry & Factory Wiring

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/evm_chains.py`
- Create: `KryptoWalletDashboard/backend/tests/test_evm_chains.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`

- [ ] **Step 1: Write the failing test for the chain registry**

`KryptoWalletDashboard/backend/tests/test_evm_chains.py`:
```python
from app.adapters.evm_chains import EVM_CHAINS


def test_evm_chains_covers_all_six_supported_chains():
    names = {chain.chain_name for chain in EVM_CHAINS}
    assert names == {"ethereum", "optimism", "bsc", "polygon", "base", "arbitrum"}


def test_evm_chains_have_unique_chain_ids():
    chain_ids = [chain.chain_id for chain in EVM_CHAINS]
    assert len(chain_ids) == len(set(chain_ids))


def test_ethereum_chain_config_matches_etherscan_v2_chain_id():
    ethereum = next(c for c in EVM_CHAINS if c.chain_name == "ethereum")
    assert ethereum.chain_id == 1
    assert ethereum.native_asset == "ETH"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_evm_chains.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.evm_chains'`.

- [ ] **Step 3: Implement `app/adapters/evm_chains.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class EvmChainConfig:
    chain_id: int
    chain_name: str
    native_asset: str


EVM_CHAINS: list[EvmChainConfig] = [
    EvmChainConfig(chain_id=1, chain_name="ethereum", native_asset="ETH"),
    EvmChainConfig(chain_id=10, chain_name="optimism", native_asset="ETH"),
    EvmChainConfig(chain_id=56, chain_name="bsc", native_asset="BNB"),
    EvmChainConfig(chain_id=137, chain_name="polygon", native_asset="MATIC"),
    EvmChainConfig(chain_id=8453, chain_name="base", native_asset="ETH"),
    EvmChainConfig(chain_id=42161, chain_name="arbitrum", native_asset="ETH"),
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_evm_chains.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Update `app/adapters/factory.py` to build one `EvmAdapter` per (wallet, chain) pair**

Replace the whole file:
```python
from app import config
from app.adapters.base import TransactionAdapter
from app.adapters.bitcoin import BitcoinAdapter
from app.adapters.evm import EvmAdapter
from app.adapters.evm_chains import EVM_CHAINS
from app.adapters.kraken import KrakenAdapter


def build_adapters_from_config() -> list[TransactionAdapter]:
    adapters: list[TransactionAdapter] = []
    for wallet in config.BITCOIN_WALLETS:
        adapters.append(BitcoinAdapter(account_label=wallet.label, address=wallet.address))
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
    if config.KRAKEN_API_KEY and config.KRAKEN_API_SECRET:
        adapters.append(
            KrakenAdapter(
                account_label="kraken-main",
                api_key=config.KRAKEN_API_KEY,
                api_secret=config.KRAKEN_API_SECRET,
            )
        )
    return adapters
```

Note: `account_label` stays the wallet's own label (e.g. `"main"`), unchanged across chains — `source_name` (the chain name) is what already differentiates one chain's rows from another's in the `(source_name, account_label, external_id)` uniqueness constraint, so no chain suffix is needed on the label itself.

- [ ] **Step 6: Write a test proving the factory produces one adapter per (wallet, chain) pair**

Check whether `KryptoWalletDashboard/backend/tests/test_factory.py` exists — it doesn't yet (Phase 1 didn't test `factory.py` directly, per its own plan's note that it's "thin config wiring"). Create it now, since this task changes factory.py's behavior in a way worth locking in:

`KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
import os

import pytest

from app import config
from app.adapters.evm import EvmAdapter
from app.adapters.evm_chains import EVM_CHAINS
from app.adapters.factory import build_adapters_from_config


@pytest.fixture()
def one_wallet_config(monkeypatch):
    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(
        config, "ETHEREUM_WALLETS", [config.WalletConfig(label="main", address="0xabc")]
    )
    monkeypatch.setattr(config, "ETHERSCAN_API_KEY", "key")
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")


def test_one_ethereum_wallet_produces_one_evm_adapter_per_chain(one_wallet_config):
    adapters = build_adapters_from_config()

    evm_adapters = [a for a in adapters if isinstance(a, EvmAdapter)]
    assert len(evm_adapters) == len(EVM_CHAINS)
    assert {a.source_name for a in evm_adapters} == {c.chain_name for c in EVM_CHAINS}
    assert all(a.account_label == "main" for a in evm_adapters)
    assert all(a.address == "0xabc" for a in evm_adapters)
```

- [ ] **Step 7: Run the new test and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: PASS (1 test).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green (the import error from Task 1's Step 6 is now resolved since `factory.py` no longer imports the deleted `EthereumAdapter`).

- [ ] **Step 8: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/evm_chains.py KryptoWalletDashboard/backend/tests/test_evm_chains.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire up all six EVM chains through the adapter factory"
```

---

### Task 4: Native-Asset Price Mapping (BNB, MATIC)

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/prices/coingecko.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_coingecko_prices.py`

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_coingecko_prices.py`:
```python
@responses.activate
def test_client_resolves_bnb_price():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/binancecoin/history",
        json={"market_data": {"current_price": {"chf": "300.0"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BNB", date(2024, 1, 15))

    assert price == Decimal("300.0")


@responses.activate
def test_client_resolves_matic_price():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/matic-network/history",
        json={"market_data": {"current_price": {"chf": "0.75"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("MATIC", date(2024, 1, 15))

    assert price == Decimal("0.75")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_coingecko_prices.py -v`
Expected: FAIL — both new tests fail because `"BNB"`/`"MATIC"` aren't in `COINGECKO_ID_MAP` yet, so `get_price_chf` returns `None` without making the expected mocked HTTP call (and `responses` will flag the registered mock as unused, or the assertion on `price` will fail comparing `None` to a `Decimal`).

- [ ] **Step 3: Add the mappings**

In `KryptoWalletDashboard/backend/app/prices/coingecko.py`, update `COINGECKO_ID_MAP`:
```python
COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "XBT": "bitcoin",
    "ETH": "ethereum",
    "ETH2": "ethereum",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
}
```

**Note for whoever implements this task:** verify `"matic-network"` is still CoinGecko's current id for Polygon's native asset at the time you implement this — Polygon rebranded its token from MATIC to POL in 2024, and CoinGecko may have introduced a separate id (e.g. `"polygon-ecosystem-token"`) for the new ticker by the time you're reading this. Check `https://api.coingecko.com/api/v3/coins/list` (or CoinGecko's docs) for the currently-correct id before assuming the value above is still right, and update both this mapping and the `native_asset="MATIC"` value in `app/adapters/evm_chains.py` (Task 3) together if the canonical symbol has changed, so they stay consistent with each other.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_coingecko_prices.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/backend/app/prices/coingecko.py KryptoWalletDashboard/backend/tests/test_coingecko_prices.py
git commit -m "feat: add CoinGecko price mapping for BNB and MATIC"
```

---

### Task 5: Update Backend Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Add a section documenting the newly-supported chains**

Insert a new section into `KryptoWalletDashboard/backend/README.md`, right after the existing "Setup" section (before "Server starten"):

```markdown
## Unterstützte EVM-Chains

Seit Phase 2a werden neben Ethereum automatisch fünf weitere EVM-Chains
für dieselbe(n) in `ETHEREUM_ADDRESSES` konfigurierte(n) Adresse(n)
mitsynchronisiert - keine zusätzliche Konfiguration nötig:

- Ethereum
- Optimism
- BNB Smart Chain (BSC)
- Polygon
- Base
- Arbitrum One

Alle sechs laufen über Etherscans vereinheitlichte Multi-Chain-API mit
demselben `ETHERSCAN_API_KEY`. Sowohl native Coin-Transfers (ETH, BNB,
MATIC, ...) als auch ERC-20-Token-Transfers (z.B. USDT, USDC) werden auf
allen sechs Chains erfasst.
```

- [ ] **Step 2: Commit**

```bash
git add KryptoWalletDashboard/backend/README.md
git commit -m "docs: document the six supported EVM chains"
```

---

## Self-Review Notes

- **Spec coverage:** All six chains via Etherscan V2 (Task 1 + 3), native + ERC-20 token transfers (Task 1 + 2), single shared address list / no new config (Task 3), `EvmAdapter` replaces `EthereumAdapter` (Task 1), price mapping for new native assets (Task 4), documentation (Task 5). Binance/Coinbase/MEXC explicitly out of scope (separate plan 2b), matches the design doc.
- **Placeholder scan:** no TBD/TODO; the one explicit "verify this at implementation time" note in Task 4 is a deliberate call-out about an external API detail that may drift over time (matches the pattern already used in the Phase 1 plan for the same reason: Etherscan/CoinGecko specifics change over time and a plan can't know their state at execution time with certainty), not a placeholder for missing design work — the fallback behavior (use `"matic-network"`) is fully specified and correct as of this plan's writing.
- **Type/signature consistency:** `EvmAdapter.__init__(account_label, address, api_key, chain_id, chain_name, native_asset)` (Task 1) is used identically in `factory.py` (Task 3) and in every test. `EvmChainConfig(chain_id, chain_name, native_asset)` (Task 3) field names match what `factory.py` reads (`chain.chain_id`, `chain.chain_name`, `chain.native_asset`). `_fetch_all_pages(action)` (Task 1) is called with `"txlist"` and `"tokentx"` (Task 2) — same method, parametrized by action string, no signature drift.
