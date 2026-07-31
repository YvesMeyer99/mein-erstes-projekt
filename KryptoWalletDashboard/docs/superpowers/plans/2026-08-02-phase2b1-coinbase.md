# Plan 2b-1 – Coinbase Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CoinbaseAdapter` that fetches buy/sell/send/receive transactions across all of a user's Coinbase App (retail) accounts, authenticated via a CDP ECDSA API key using short-lived ES256 JWTs, and wires it into the existing sync pipeline alongside Bitcoin/EVM/Kraken.

**Architecture:** A standalone JWT-building helper (`app/adapters/coinbase_auth.py`) isolated from HTTP/adapter concerns, consumed by `CoinbaseAdapter` (`app/adapters/coinbase.py`), which follows the same `TransactionAdapter` interface and cursor-based pagination pattern already established by the Bitcoin/Ethereum/Kraken adapters. `factory.py` adds one `CoinbaseAdapter` instance when both new config vars are set.

**Tech Stack:** Same as Phase 1/2a — Python, `requests`, `responses` for test mocking, pytest. New dependency: `PyJWT[crypto]` (ES256 JWT signing needs the `cryptography` backend, which `PyJWT` does not vendor itself).

**Related docs:**
- [`docs/superpowers/specs/2026-08-02-phase2b1-coinbase-design.md`](../specs/2026-08-02-phase2b1-coinbase-design.md)
- [`docs/superpowers/plans/2026-07-30-backend-phase1.md`](2026-07-30-backend-phase1.md) (Phase 1)
- [`docs/superpowers/plans/2026-08-01-phase2a-evm-chains.md`](2026-08-01-phase2a-evm-chains.md) (Phase 2a)

**Scope notes (decided during planning):**
- **Coinbase App API (retail) only** — not Coinbase Advanced Trade, not Coinbase Prime. Those would need different auth/endpoints and are out of scope.
- **Binance and MEXC are separate, later plans** (2b-2, 2b-3), per the user's explicit "one exchange at a time" decision.
- **Multi-account handling:** the adapter automatically discovers all of the user's Coinbase accounts via `GET /v2/accounts` and fetches transactions for each — no per-currency configuration needed, matching the confirmed design decision.
- **CHF pricing is NOT sourced from Coinbase's own `native_amount` field.** Coinbase's `native_amount` reflects the user's Coinbase-configured native currency (not guaranteed to be CHF), so this adapter only produces `NormalizedTransaction`s with `asset`/`amount`/`fee_amount`/`fee_asset` — CHF valuation continues to flow through the existing CoinGecko price-enrichment path in `sync.py`, unchanged.
- **Unrecognized Coinbase transaction `type` values are silently skipped** — same accepted pattern already established (and reviewed) for Kraken's `NON_TRADE_TYPE_MAP` in Phase 1.
- **Only `status == "completed"` transactions are recorded** — pending/failed transactions are skipped, matching how the Bitcoin/Ethereum adapters only record confirmed transactions.
- **API research caveat:** Coinbase's documented endpoint shapes (fields, pagination, exact `type` values) were verified against `docs.cdp.coinbase.com` on 2026-08-02, but Coinbase's API surface changes over time. If the endpoint shapes below don't match reality by the time this is implemented, treat the design's *intent* (fetch all accounts, fetch each account's transactions, normalize by signed amount + type) as authoritative and adjust field names/paths to match current docs — this is the same kind of "verify against current external API docs" caveat already used for the Bitcoin/Kraken pagination details and the CoinGecko `matic-network` id in earlier plans.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      coinbase_auth.py    # NEW — ES256 JWT builder for CDP API key auth
      coinbase.py           # NEW — CoinbaseAdapter (accounts + transactions + normalization)
      factory.py              # MODIFIED — build CoinbaseAdapter when configured
    config.py                  # MODIFIED — COINBASE_API_KEY_NAME / COINBASE_API_PRIVATE_KEY
  requirements.txt              # MODIFIED — add PyJWT[crypto]
  .env.example                    # MODIFIED — document new Coinbase config vars
  README.md                        # MODIFIED — document Coinbase setup + required scopes
  tests/
    test_coinbase_auth.py          # NEW — JWT construction/signing tests
    test_coinbase_adapter.py        # NEW — adapter behavior tests
```

---

### Task 1: Coinbase JWT Authentication Helper

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/coinbase_auth.py`
- Test: `KryptoWalletDashboard/backend/tests/test_coinbase_auth.py`
- Modify: `KryptoWalletDashboard/backend/requirements.txt`

- [ ] **Step 1: Add the new dependency**

Add this line to `KryptoWalletDashboard/backend/requirements.txt` (keep existing lines, alphabetical order not required — append is fine):
```
PyJWT[crypto]
```

Run (from `KryptoWalletDashboard/backend/`):
```bash
.venv/Scripts/pip install -r requirements.txt
```
Expected: `PyJWT` and `cryptography` install without error (if `cryptography` isn't already present as a transitive dependency of something else).

- [ ] **Step 2: Write the failing tests**

`KryptoWalletDashboard/backend/tests/test_coinbase_auth.py`:
```python
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.adapters.coinbase_auth import build_coinbase_jwt


def _generate_test_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return private_pem, private_key.public_key()


def test_jwt_has_correct_header_and_payload_claims():
    private_pem, public_key = _generate_test_key_pair()
    api_key_name = "organizations/org123/apiKeys/key456"

    token = build_coinbase_jwt(
        api_key_name=api_key_name,
        private_key_pem=private_pem,
        method="GET",
        host="api.coinbase.com",
        path="/v2/accounts",
    )

    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["typ"] == "JWT"
    assert header["kid"] == api_key_name
    assert isinstance(header["nonce"], str) and len(header["nonce"]) > 0

    payload = pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})
    assert payload["iss"] == "cdp"
    assert payload["sub"] == api_key_name
    assert payload["uri"] == "GET api.coinbase.com/v2/accounts"


def test_jwt_is_verifiable_with_the_matching_public_key():
    private_pem, public_key = _generate_test_key_pair()
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    # Should not raise.
    pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})


def test_jwt_rejects_verification_with_a_different_public_key():
    private_pem, _ = _generate_test_key_pair()
    _, other_public_key = _generate_test_key_pair()
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, other_public_key, algorithms=["ES256"], options={"verify_exp": False})


def test_jwt_expires_120_seconds_after_issuance():
    private_pem, public_key = _generate_test_key_pair()
    before = int(time.time())
    token = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")
    after = int(time.time())

    payload = pyjwt.decode(token, public_key, algorithms=["ES256"], options={"verify_exp": False})
    assert before <= payload["nbf"] <= after
    assert payload["exp"] == payload["nbf"] + 120


def test_two_calls_produce_different_nonces():
    private_pem, _ = _generate_test_key_pair()
    token_a = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")
    token_b = build_coinbase_jwt("key-name", private_pem, "GET", "api.coinbase.com", "/v2/accounts")

    assert pyjwt.get_unverified_header(token_a)["nonce"] != pyjwt.get_unverified_header(token_b)["nonce"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_coinbase_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.coinbase_auth'`.

- [ ] **Step 4: Implement `app/adapters/coinbase_auth.py`**

```python
import secrets
import time

import jwt as pyjwt


def build_coinbase_jwt(
    api_key_name: str,
    private_key_pem: str,
    method: str,
    host: str,
    path: str,
) -> str:
    """Build a short-lived ES256 JWT for authenticating one Coinbase App API
    request, per Coinbase's CDP API key authentication scheme. A fresh JWT
    must be built for every request - it expires 120 seconds after issuance
    and is scoped to one specific method+host+path via the `uri` claim."""
    now = int(time.time())
    payload = {
        "iss": "cdp",
        "sub": api_key_name,
        "nbf": now,
        "exp": now + 120,
        "uri": f"{method} {host}{path}",
    }
    headers = {
        "kid": api_key_name,
        "nonce": secrets.token_hex(16),
    }
    return pyjwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_coinbase_auth.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/coinbase_auth.py KryptoWalletDashboard/backend/tests/test_coinbase_auth.py KryptoWalletDashboard/backend/requirements.txt
git commit -m "feat: Coinbase CDP JWT authentication helper"
```

---

### Task 2: `CoinbaseAdapter`

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/coinbase.py`
- Test: `KryptoWalletDashboard/backend/tests/test_coinbase_adapter.py`

**Data source:** Coinbase App API v2, `https://api.coinbase.com`. `GET /v2/accounts` (list all accounts, cursor-paginated via `starting_after`). `GET /v2/accounts/{account_id}/transactions` (list transactions for one account, same pagination style). Each transaction has `id`, `type` (`"buy"`, `"sell"`, `"send"`, `"receive"`, `"transfer"`, possibly others), `status`, `amount` (`{"amount": "<signed decimal string>", "currency": "<asset>"}`), optionally `fee` (`{"amount": "...", "currency": "..."}`), `created_at` (ISO8601 with `Z` suffix).

- [ ] **Step 1: Write the failing tests**

`KryptoWalletDashboard/backend/tests/test_coinbase_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.coinbase import CoinbaseAdapter

API_BASE = "https://api.coinbase.com"


def _account(account_id, currency):
    return {"id": account_id, "name": f"{currency} Wallet", "currency": currency}


def _accounts_page(accounts):
    return {"pagination": {}, "data": accounts}


def _tx(tx_id, tx_type, amount, currency, created_at, status="completed", fee=None):
    tx = {
        "id": tx_id,
        "type": tx_type,
        "status": status,
        "amount": {"amount": str(amount), "currency": currency},
        "created_at": created_at,
    }
    if fee is not None:
        tx["fee"] = fee
    return tx


def _transactions_page(transactions):
    return {"pagination": {}, "data": transactions}


def _mock_accounts(accounts):
    responses.add(
        responses.GET,
        f"{API_BASE}/v2/accounts",
        json=_accounts_page(accounts),
        status=200,
    )


def _mock_transactions(account_id, transactions):
    responses.add(
        responses.GET,
        f"{API_BASE}/v2/accounts/{account_id}/transactions",
        json=_transactions_page(transactions),
        status=200,
    )


def _adapter():
    return CoinbaseAdapter(
        account_label="coinbase-main",
        api_key_name="organizations/org/apiKeys/key",
        private_key_pem="dummy-not-a-real-key",
    )


@responses.activate
def test_buy_transaction_maps_to_buy_type(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx1", "buy", "0.5", "BTC", "2024-01-15T10:00:00Z")],
    )

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "buy"
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.5")
    assert tx.source_name == "coinbase"
    assert tx.external_id == "tx1"


@responses.activate
def test_sell_transaction_maps_to_sell_type(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx2", "sell", "-0.2", "BTC", "2024-01-15T11:00:00Z")],
    )

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "sell"
    assert results[0].amount == Decimal("0.2")


@responses.activate
def test_positive_send_is_transfer_in_negative_send_is_transfer_out(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-eth", "ETH")])
    _mock_transactions(
        "acc-eth",
        [
            _tx("tx-in", "receive", "1.0", "ETH", "2024-01-15T09:00:00Z"),
            _tx("tx-out", "send", "-0.3", "ETH", "2024-01-15T09:30:00Z"),
        ],
    )

    results = _adapter().fetch_transactions(None)

    by_id = {r.external_id: r for r in results}
    assert by_id["tx-in"].tx_type == "transfer_in"
    assert by_id["tx-in"].amount == Decimal("1.0")
    assert by_id["tx-out"].tx_type == "transfer_out"
    assert by_id["tx-out"].amount == Decimal("0.3")


@responses.activate
def test_unrecognized_type_is_skipped(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx-weird", "staking_reward_v2_beta", "0.001", "BTC", "2024-01-15T10:00:00Z")],
    )

    assert _adapter().fetch_transactions(None) == []


@responses.activate
def test_non_completed_status_is_skipped(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx-pending", "buy", "0.1", "BTC", "2024-01-15T10:00:00Z", status="pending")],
    )

    assert _adapter().fetch_transactions(None) == []


@responses.activate
def test_fee_is_captured_when_present(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [
            _tx(
                "tx-fee",
                "buy",
                "0.5",
                "BTC",
                "2024-01-15T10:00:00Z",
                fee={"amount": "1.50", "currency": "EUR"},
            )
        ],
    )

    results = _adapter().fetch_transactions(None)

    assert results[0].fee_amount == Decimal("1.50")
    assert results[0].fee_asset == "EUR"


@responses.activate
def test_since_filters_out_older_transactions(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [
            _tx("tx-old", "buy", "0.1", "BTC", "2024-01-01T00:00:00Z"),
            _tx("tx-new", "buy", "0.2", "BTC", "2024-06-01T00:00:00Z"),
        ],
    )

    since = datetime(2024, 3, 1, tzinfo=timezone.utc)
    results = _adapter().fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-new"]


@responses.activate
def test_iterates_transactions_across_multiple_accounts(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC"), _account("acc-eth", "ETH")])
    _mock_transactions("acc-btc", [_tx("tx-btc", "buy", "0.1", "BTC", "2024-01-15T10:00:00Z")])
    _mock_transactions("acc-eth", [_tx("tx-eth", "buy", "1.0", "ETH", "2024-01-15T10:00:00Z")])

    results = _adapter().fetch_transactions(None)

    assert {r.external_id for r in results} == {"tx-btc", "tx-eth"}


@responses.activate
def test_paginates_accounts_and_transactions_until_short_page(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    page1_accounts = [_account(f"acc-{i}", "BTC") for i in range(CoinbaseAdapter.PAGE_LIMIT)]
    page2_accounts = [_account("acc-last", "ETH")]
    responses.add(responses.GET, f"{API_BASE}/v2/accounts", json=_accounts_page(page1_accounts), status=200)
    responses.add(responses.GET, f"{API_BASE}/v2/accounts", json=_accounts_page(page2_accounts), status=200)
    for account in page1_accounts + page2_accounts:
        _mock_transactions(account["id"], [])

    _adapter().fetch_transactions(None)

    account_calls = [c for c in responses.calls if c.request.url.split("?")[0] == f"{API_BASE}/v2/accounts"]
    assert len(account_calls) == 2
    assert "starting_after=acc-" in account_calls[1].request.url
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_coinbase_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.coinbase'`.

- [ ] **Step 3: Implement `app/adapters/coinbase.py`**

```python
import json
from datetime import datetime
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.adapters.coinbase_auth import build_coinbase_jwt
from app.schemas import NormalizedTransaction

HOST = "api.coinbase.com"

DIRECT_TYPE_MAP = {"buy": "buy", "sell": "sell"}
TRANSFER_TYPES = {"send", "receive", "transfer"}


class CoinbaseAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "coinbase"
    PAGE_LIMIT = 25

    def __init__(self, account_label: str, api_key_name: str, private_key_pem: str):
        super().__init__(account_label)
        self.api_key_name = api_key_name
        self.private_key_pem = private_key_pem

    def _get(self, path: str, params: dict) -> dict:
        token = build_coinbase_jwt(self.api_key_name, self.private_key_pem, "GET", HOST, path)
        response = requests.get(
            f"https://{HOST}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _paginated(self, path: str) -> list[dict]:
        items: list[dict] = []
        starting_after = None
        while True:
            params: dict = {"limit": self.PAGE_LIMIT}
            if starting_after is not None:
                params["starting_after"] = starting_after
            data = self._get(path, params)
            batch = data.get("data", [])
            items.extend(batch)
            if len(batch) < self.PAGE_LIMIT:
                break
            starting_after = batch[-1]["id"]
        return items

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for account in self._paginated("/v2/accounts"):
            for tx in self._paginated(f"/v2/accounts/{account['id']}/transactions"):
                normalized = self._normalize(tx, since)
                if normalized is not None:
                    results.append(normalized)
        return results

    def _normalize(self, tx: dict, since: datetime | None) -> NormalizedTransaction | None:
        if tx.get("status") != "completed":
            return None

        timestamp = datetime.fromisoformat(tx["created_at"].replace("Z", "+00:00"))
        if since is not None and timestamp <= since:
            return None

        amount_obj = tx["amount"]
        signed_amount = Decimal(amount_obj["amount"])
        asset = amount_obj["currency"]

        tx_type = DIRECT_TYPE_MAP.get(tx["type"])
        if tx_type is None:
            if tx["type"] not in TRANSFER_TYPES:
                return None
            tx_type = "transfer_in" if signed_amount > 0 else "transfer_out"

        fee_amount = None
        fee_asset = None
        fee = tx.get("fee")
        if fee is not None:
            fee_amount = Decimal(fee["amount"])
            fee_asset = fee["currency"]

        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset=asset,
            amount=abs(signed_amount),
            fee_amount=fee_amount,
            fee_asset=fee_asset,
            external_id=tx["id"],
            raw_json=json.dumps(tx),
        )
```

**Note:** the tests above `monkeypatch` `app.adapters.coinbase.build_coinbase_jwt` to a fixed fake token, since the real function needs a valid EC PEM key to sign anything (Task 1's tests already cover the JWT builder's own correctness in isolation) — this test file is only exercising the adapter's HTTP/pagination/normalization logic, not real JWT signing, so a dummy `private_key_pem="dummy-not-a-real-key"` in the test adapter is fine as long as `build_coinbase_jwt` itself is patched out.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_coinbase_adapter.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/coinbase.py KryptoWalletDashboard/backend/tests/test_coinbase_adapter.py
git commit -m "feat: Coinbase adapter for buy/sell/send/receive transactions"
```

---

### Task 3: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Write the failing test for the new config parsing**

Append to `KryptoWalletDashboard/backend/tests/test_config.py`:
```python
def test_coinbase_private_key_converts_escaped_newlines_to_real_newlines():
    from app.config import normalize_pem_env_value

    escaped = "-----BEGIN EC PRIVATE KEY-----\\nABC123\\n-----END EC PRIVATE KEY-----\\n"
    result = normalize_pem_env_value(escaped)

    assert result == "-----BEGIN EC PRIVATE KEY-----\nABC123\n-----END EC PRIVATE KEY-----\n"


def test_normalize_pem_env_value_returns_empty_string_for_none():
    from app.config import normalize_pem_env_value

    assert normalize_pem_env_value(None) == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_pem_env_value'`.

- [ ] **Step 3: Add the new config values to `app/config.py`**

Add this function and these two module-level constants to `KryptoWalletDashboard/backend/app/config.py` (after `parse_wallets`, before the existing module-level constant assignments):
```python
def normalize_pem_env_value(env_value: str | None) -> str:
    """PEM private keys are multi-line; when stored in a .env file they're
    typically written with literal backslash-n sequences instead of real
    newlines. Convert those back to real newlines so the value is usable
    directly as a PEM string."""
    if not env_value:
        return ""
    return env_value.replace("\\n", "\n")
```

Add alongside the other module-level constants at the bottom of the file:
```python
COINBASE_API_KEY_NAME = os.getenv("COINBASE_API_KEY_NAME", "")
COINBASE_API_PRIVATE_KEY = normalize_pem_env_value(os.getenv("COINBASE_API_PRIVATE_KEY"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

- [ ] **Step 5: Write the failing test for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_coinbase_adapter_is_added_when_configured(monkeypatch):
    from app.adapters.coinbase import CoinbaseAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "fake-pem")

    adapters = build_adapters_from_config()

    coinbase_adapters = [a for a in adapters if isinstance(a, CoinbaseAdapter)]
    assert len(coinbase_adapters) == 1
    assert coinbase_adapters[0].account_label == "coinbase-main"
    assert coinbase_adapters[0].api_key_name == "organizations/org/apiKeys/key"


def test_coinbase_adapter_is_not_added_when_only_partially_configured(monkeypatch):
    from app.adapters.coinbase import CoinbaseAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "organizations/org/apiKeys/key")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, CoinbaseAdapter) for a in adapters)
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `CoinbaseAdapter` import succeeds (Task 2 already created it), but `build_adapters_from_config()` never builds one, so `len(coinbase_adapters) == 1` fails (actual: 0).

- [ ] **Step 7: Wire `CoinbaseAdapter` into `app/adapters/factory.py`**

Modify `app/adapters/factory.py` — add the import and the conditional block (after the existing Kraken block):
```python
from app.adapters.coinbase import CoinbaseAdapter
```

```python
    if config.COINBASE_API_KEY_NAME and config.COINBASE_API_PRIVATE_KEY:
        adapters.append(
            CoinbaseAdapter(
                account_label="coinbase-main",
                api_key_name=config.COINBASE_API_KEY_NAME,
                private_key_pem=config.COINBASE_API_PRIVATE_KEY,
            )
        )
```

- [ ] **Step 8: Run the new tests and the full suite**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests green.

- [ ] **Step 9: Commit**

```bash
git add KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/tests/test_config.py KryptoWalletDashboard/backend/tests/test_factory.py
git commit -m "feat: wire Coinbase adapter into config and factory"
```

---

### Task 4: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document the new config vars in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example` (after the existing Kraken section):
```
# Coinbase (App/Retail API): CDP Secret API Key with an ECDSA (P-256) key type.
# Grant ONLY the read-only scopes: wallet:accounts:read, wallet:transactions:read
# (no trade/send/withdraw permissions!). The private key is multi-line PEM -
# write it here with literal \n instead of real line breaks.
COINBASE_API_KEY_NAME=organizations/your-org-id/apiKeys/your-key-id
COINBASE_API_PRIVATE_KEY=-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END EC PRIVATE KEY-----\n
```

- [ ] **Step 2: Document Coinbase setup in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, near the existing "Unterstützte EVM-Chains" section:
```markdown
## Coinbase

Zusätzlich zu Bitcoin/EVM-Chains/Kraken wird automatisch dein Coinbase-
App-Account (Retail, nicht Advanced Trade) mitsynchronisiert, sobald
`COINBASE_API_KEY_NAME` und `COINBASE_API_PRIVATE_KEY` gesetzt sind. Alle
Krypto-Konten (BTC, ETH, ...) werden automatisch erkannt - keine manuelle
Konten-Liste nötig. Fiat-Konten (EUR, CHF, USD, GBP, JPY, CAD, AUD) werden
bewusst übersprungen (auch keine Transaktions-Abfrage dafür), da sie für
die Krypto-Steuerbetrachtung nicht relevant sind und ihre Buy/Sell-Zeilen
sonst mit falschem Vorzeichen im Portfolio landen könnten.

**Wichtig beim Anlegen des API-Keys:**
- CDP Secret API Key mit **ECDSA-Schlüsseltyp** anlegen (nicht den seit
  2025 defaultmäßigen Ed25519-Key - der wird von dieser API nicht
  unterstützt).
- Nur die Lese-Scopes `wallet:accounts:read` und
  `wallet:transactions:read` vergeben - keine Trade-/Sende-/
  Auszahlungsrechte.
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document Coinbase setup and required read-only scopes"
```

---

## Self-Review Notes

- **Spec coverage:** JWT auth (Task 1), account+transaction fetching with pagination (Task 2), buy/sell/transfer normalization + fee capture + status/since filtering (Task 2), multi-account auto-discovery (Task 2), config/factory wiring (Task 3), documentation including the read-only-scope security reminder (Task 4). Matches the design doc's scope exactly; Advanced Trade/Prime/Binance/MEXC correctly excluded.
- **Placeholder scan:** no TBD/TODO. The plan's own "API research caveat" (in the header) is a deliberate, explicit call-out about external API drift risk — same pattern already used and accepted in the Phase 1 and Phase 2a plans — not a placeholder for missing design work.
- **Type/signature consistency:** `build_coinbase_jwt(api_key_name, private_key_pem, method, host, path)` (Task 1) is called identically inside `CoinbaseAdapter._get` (Task 2). `CoinbaseAdapter.__init__(account_label, api_key_name, private_key_pem)` (Task 2) matches exactly how `factory.py` constructs it (Task 3). `config.COINBASE_API_KEY_NAME`/`config.COINBASE_API_PRIVATE_KEY` (Task 3) match the names used in `factory.py`'s conditional and in `.env.example`/README (Task 4).
