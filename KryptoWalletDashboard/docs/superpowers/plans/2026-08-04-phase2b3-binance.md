# Plan 2b-3 – Binance Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `BinanceAdapter` that fetches successful deposits/withdrawals automatically (windowed to Binance's 90-day-per-query limit) and complete trade history for manually-configured trading pairs (via unbounded `fromId` pagination), authenticated via Binance's HMAC-SHA256 query-signing scheme, wired into the existing sync pipeline alongside Bitcoin/EVM/Kraken/Coinbase/MEXC.

**Architecture:** A standalone HMAC-signing helper (`app/adapters/binance_auth.py`) isolated from HTTP/adapter concerns, consumed by `BinanceAdapter` (`app/adapters/binance.py`), which follows the same `TransactionAdapter` interface as the sibling adapters. Deposits/withdrawals are asset-agnostic (no configuration needed) but Binance caps every deposit/withdrawal query to a 90-day window, so the adapter walks 90-day windows from a start point up to "now"; trades require the user to configure which trading pairs to track (Binance's trade-history endpoint requires an explicit `symbol` per call, same constraint as MEXC), but unlike MEXC, Binance's `fromId`-based pagination has no 30-day cap, so the full trade history is always retrievable.

**Tech Stack:** Same as Phase 1/2a/2b-1/2b-2 — Python, `requests`, `responses` for test mocking, pytest. No new dependencies (HMAC-SHA256 is stdlib `hmac`/`hashlib`, same as Kraken's/MEXC's adapters).

**Related docs:**
- [`docs/superpowers/specs/2026-08-04-phase2b3-binance-design.md`](../specs/2026-08-04-phase2b3-binance-design.md)
- [`docs/superpowers/plans/2026-08-03-phase2b2-mexc.md`](2026-08-03-phase2b2-mexc.md) (Plan 2b-2, near-identical auth/adapter-split pattern and the `SYNC_LOOKBACK` watermark fix this plan builds in from the start)

**Scope notes (decided during planning):**
- **Trading pairs must be manually configured** (`BINANCE_TRADING_PAIRS`, same `SYMBOL:BASE:QUOTE` format as MEXC's `MEXC_TRADING_PAIRS`), because Binance's `GET /api/v3/myTrades` requires a mandatory `symbol` parameter — there is no "list all trades across all pairs" endpoint. The existing `parse_trading_pairs()` / `TradingPairConfig` from `app/config.py` (added in Plan 2b-2) are reused as-is — no new parsing function needed for pairs.
- **Deposits/withdrawals are capped to a 90-day window per API call** (`startTime`/`endTime` can't span more than 90 days), unlike MEXC which allows arbitrarily long ranges in one call. The adapter therefore walks 90-day windows from a start point to "now", with `offset`-based pagination inside each window for windows with >1000 records.
- **No "give me everything" mode for deposits/withdrawals**: without `startTime`, Binance defaults to the last 90 days only. A new optional `BINANCE_SYNC_START` config var (ISO date, e.g. account creation date) seeds the very first sync's window start; if unset, a fallback of 5 years before "now" is used. This has no equivalent in MEXC's design (MEXC allows unbounded ranges by simply omitting `startTime`).
- **Trades have no 30-day cap, unlike MEXC.** `GET /api/v3/myTrades` supports `fromId`-based pagination (trade ID cursor) with no time-window restriction — only the `startTime`+`endTime` query mode is capped at 24 hours, and this plan doesn't use that mode. The adapter always walks the full trade history per configured pair via `fromId`, relying on `sync.py`'s existing `external_id` dedup to avoid reprocessing already-stored trades on every subsequent sync. No 30-day documentation warning is needed (unlike MEXC's Task 5).
- **The `SYNC_LOOKBACK` watermark-safety pattern (discovered as a bug in Coinbase and MEXC's *final* reviews) is built into this adapter from Task 2 onward**, not discovered later: a pending deposit/withdrawal that completes after the sync watermark has already advanced (due to a faster-completing sibling stream) must still be picked up on the next sync. `SYNC_LOOKBACK = timedelta(days=7)` widens the effective window start on every incremental sync.
- **Testability of the 90-day windowing requires an injectable clock.** Since window-splitting depends on "now" and tests must be deterministic, `BinanceAdapter` accepts an optional `clock: Callable[[], datetime]` constructor parameter (defaulting to `lambda: datetime.now(timezone.utc)`), analogous to how `sync.py` already takes an injected `price_client`. Production code never passes `clock` explicitly (uses the default); tests inject a fixed value.
- **API research caveat:** Binance's documented endpoint shapes (fields, status codes, pagination, window limits) were verified against `developers.binance.com`'s REST API docs and `github.com/binance/binance-spot-api-docs` on 2026-08-04, but external API docs can drift. If shapes don't match reality by implementation time, treat the design's *intent* (HMAC-signed requests, status-code filtering, per-pair trade fetching, windowed deposit/withdrawal pagination) as authoritative and adjust field names/codes to match current docs — same caveat pattern already used in prior plans for other external APIs.

---

## File Structure

```
KryptoWalletDashboard/backend/
  app/
    adapters/
      binance_auth.py         # NEW — HMAC-SHA256 signing helper for Binance requests
      binance.py               # NEW — BinanceAdapter (deposits, withdrawals, trades)
      factory.py                  # MODIFIED — build BinanceAdapter when configured
    config.py                      # MODIFIED — BINANCE_API_KEY / BINANCE_API_SECRET / BINANCE_TRADING_PAIRS / BINANCE_SYNC_START
  .env.example                      # MODIFIED — document new Binance config vars
  README.md                          # MODIFIED — document Binance setup
  tests/
    test_binance_auth.py                # NEW — signing tests
    test_binance_adapter.py              # NEW — adapter behavior tests
```

---

### Task 1: Binance HMAC Signing Helper

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/binance_auth.py`
- Test: `KryptoWalletDashboard/backend/tests/test_binance_auth.py`

- [ ] **Step 1: Write the failing tests**

`KryptoWalletDashboard/backend/tests/test_binance_auth.py`:
```python
import hashlib
import hmac

from app.adapters.binance_auth import build_signed_params, sign_binance_params


def test_sign_binance_params_computes_correct_hmac_sha256_hex():
    params = {"symbol": "BTCUSDT", "timestamp": 1644489390087}
    secret = "45d0b3c26f2644f19bfb98b07741b2f5"

    signature = sign_binance_params(params, secret)

    expected = hmac.new(
        secret.encode(),
        "symbol=BTCUSDT&timestamp=1644489390087".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected


def test_sign_binance_params_is_lowercase_hex():
    signature = sign_binance_params({"a": "1"}, "secret")

    assert signature == signature.lower()
    assert all(c in "0123456789abcdef" for c in signature)


def test_build_signed_params_adds_timestamp_and_signature():
    result = build_signed_params({"symbol": "BTCUSDT"}, "secret")

    assert "timestamp" in result and isinstance(result["timestamp"], int)
    assert "signature" in result
    assert result["symbol"] == "BTCUSDT"


def test_build_signed_params_signature_matches_manual_computation():
    result = build_signed_params({"symbol": "BTCUSDT"}, "secret")

    params_without_signature = {k: v for k, v in result.items() if k != "signature"}
    expected = sign_binance_params(params_without_signature, "secret")
    assert result["signature"] == expected


def test_different_secrets_produce_different_signatures():
    sig_a = sign_binance_params({"a": "1"}, "secret-a")
    sig_b = sign_binance_params({"a": "1"}, "secret-b")

    assert sig_a != sig_b


def test_different_params_produce_different_signatures():
    sig_a = sign_binance_params({"symbol": "BTCUSDT"}, "secret")
    sig_b = sign_binance_params({"symbol": "ETHUSDT"}, "secret")

    assert sig_a != sig_b
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `KryptoWalletDashboard/backend/`): `.venv/Scripts/pytest tests/test_binance_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.binance_auth'`.

- [ ] **Step 3: Implement `app/adapters/binance_auth.py`**

```python
import hashlib
import hmac
import time
import urllib.parse


def sign_binance_params(params: dict, secret: str) -> str:
    """Compute a Binance Spot API v3 request signature: HMAC-SHA256 of the
    URL-encoded query string, keyed with the API secret, as lowercase
    hex - per Binance's documented signing scheme (identical algorithm to
    MEXC's, which mirrors Binance's API design).

    Note: `params` values must be scalar (str/int/etc.), not lists/tuples/
    dicts - `urllib.parse.urlencode` is called without `doseq=True`. This
    codebase's Binance calls only ever pass scalar values (symbol strings,
    timestamps, limits, offsets)."""
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def build_signed_params(params: dict, secret: str) -> dict:
    """Return a new params dict with a fresh millisecond timestamp and
    the computed signature attached, ready to send as a signed Binance
    request's query parameters."""
    signed = dict(params)
    signed["timestamp"] = int(time.time() * 1000)
    signed["signature"] = sign_binance_params(signed, secret)
    return signed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_binance_auth.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/binance_auth.py KryptoWalletDashboard/backend/tests/test_binance_auth.py
git commit -m "feat: Binance HMAC-SHA256 request signing helper"
```

---

### Task 2: `BinanceAdapter` — Deposits & Withdrawals (90-day windowed, watermark-safe)

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/binance.py`
- Test: `KryptoWalletDashboard/backend/tests/test_binance_adapter.py`

**Data source:** Binance Spot/Wallet API, `https://api.binance.com`. `GET /sapi/v1/capital/deposit/hisrec` (deposits: `startTime`, `endTime`, `offset`, `limit`, max `limit=1000`, **max 90 days between `startTime`/`endTime`**). `GET /sapi/v1/capital/withdraw/history` (withdrawals, same pagination style, same 90-day cap). Deposit `status` code `1` = successfully credited (others skipped). Withdrawal `status` code `6` = completed (others skipped).

- [ ] **Step 1: Write the failing tests**

`KryptoWalletDashboard/backend/tests/test_binance_adapter.py`:
```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import responses

from app.adapters.binance import BinanceAdapter

API_BASE = "https://api.binance.com"
NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _deposit(record_id, coin, amount, status, insert_time_ms):
    return {
        "id": record_id,
        "amount": str(amount),
        "coin": coin,
        "network": "BSC",
        "status": status,
        "txId": f"tx-{record_id}",
        "insertTime": insert_time_ms,
    }


def _withdrawal(record_id, coin, amount, status, apply_time_ms, fee="0"):
    return {
        "id": record_id,
        "coin": coin,
        "amount": str(amount),
        "transactionFee": str(fee),
        "status": status,
        "applyTime": apply_time_ms,
    }


def _mock_get(path, payload):
    responses.add(responses.GET, f"{API_BASE}{path}", json=payload, status=200)


def _query(call):
    return parse_qs(urlparse(call.request.url).query)


def _adapter(trading_pairs=None, sync_start=None, now=NOW):
    return BinanceAdapter(
        account_label="binance-main",
        api_key="key",
        api_secret="secret",
        trading_pairs=trading_pairs or [],
        sync_start=sync_start,
        clock=lambda: now,
    )


def _ms(dt):
    return int(dt.timestamp() * 1000)


@responses.activate
def test_successful_deposit_status_1_is_transfer_in():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [_deposit("d1", "BTC", "0.5", 1, _ms(NOW - timedelta(days=1)))])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    deposits = [r for r in results if r.tx_type == "transfer_in"]
    assert len(deposits) == 1
    tx = deposits[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.5")
    assert tx.source_name == "binance"
    assert tx.external_id == "deposit-d1"


@responses.activate
def test_non_success_deposit_status_is_skipped():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [_deposit("d2", "BTC", "0.1", 0, _ms(NOW - timedelta(days=1)))])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "transfer_in"] == []


@responses.activate
def test_successful_withdrawal_status_6_is_transfer_out_with_fee():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w1", "BTC", "0.2", 6, _ms(NOW - timedelta(days=1)), fee="0.0005")],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    withdrawals = [r for r in results if r.tx_type == "transfer_out"]
    assert len(withdrawals) == 1
    tx = withdrawals[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.2")
    assert tx.fee_amount == Decimal("0.0005")
    assert tx.fee_asset == "BTC"
    assert tx.external_id == "withdrawal-w1"


@responses.activate
def test_non_success_withdrawal_status_is_skipped():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w2", "BTC", "0.1", 0, _ms(NOW - timedelta(days=1)))],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "transfer_out"] == []


@responses.activate
def test_zero_withdrawal_fee_is_not_recorded():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w3", "BTC", "0.1", 6, _ms(NOW - timedelta(days=1)), fee="0")],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    tx = [r for r in results if r.tx_type == "transfer_out"][0]
    assert tx.fee_amount is None
    assert tx.fee_asset is None


@responses.activate
def test_first_sync_uses_configured_sync_start_as_window_start():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    sync_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    _adapter(sync_start=sync_start, now=sync_start + timedelta(days=30)).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 1
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(sync_start)
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(sync_start + timedelta(days=30))


@responses.activate
def test_first_sync_falls_back_to_five_years_when_sync_start_not_configured():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    _adapter(sync_start=None, now=NOW).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    expected_start = _ms(NOW - timedelta(days=365 * 5))
    assert int(_query(deposit_calls[0])["startTime"][0]) == expected_start


@responses.activate
def test_incremental_sync_widens_window_by_seven_day_lookback():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    since = NOW - timedelta(days=10)

    _adapter(now=NOW).fetch_transactions(since)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(since - timedelta(days=7))
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(NOW)


@responses.activate
def test_incremental_sync_excludes_records_at_or_before_effective_since():
    since = NOW - timedelta(days=10)
    effective_since = since - timedelta(days=7)
    _mock_get(
        "/sapi/v1/capital/deposit/hisrec",
        [
            _deposit("d-old", "BTC", "0.1", 1, _ms(effective_since)),
            _deposit("d-new", "BTC", "0.2", 1, _ms(effective_since + timedelta(seconds=1))),
        ],
    )
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(now=NOW).fetch_transactions(since)

    assert [r.external_id for r in results] == ["deposit-d-new"]


@responses.activate
def test_splits_into_multiple_90_day_windows_when_gap_is_large():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    sync_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    now = datetime(2020, 5, 1, tzinfo=timezone.utc)  # 121 days later -> 2 windows

    _adapter(sync_start=sync_start, now=now).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 2
    first_window_end = sync_start + timedelta(days=90)
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(sync_start)
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(first_window_end)
    assert int(_query(deposit_calls[1])["startTime"][0]) == _ms(first_window_end) + 1
    assert int(_query(deposit_calls[1])["endTime"][0]) == _ms(now)


@responses.activate
def test_paginates_within_a_window_via_offset_until_short_page():
    full_page = [_deposit(f"d-{i}", "BTC", "0.01", 1, _ms(NOW - timedelta(days=1))) for i in range(1000)]
    short_page = [_deposit("d-last", "BTC", "0.01", 1, _ms(NOW - timedelta(days=1)))]
    responses.add(responses.GET, f"{API_BASE}/sapi/v1/capital/deposit/hisrec", json=full_page, status=200)
    responses.add(responses.GET, f"{API_BASE}/sapi/v1/capital/deposit/hisrec", json=short_page, status=200)
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10), now=NOW).fetch_transactions(None)

    deposits = [r for r in results if r.tx_type == "transfer_in"]
    assert len(deposits) == 1001
    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 2
    assert _query(deposit_calls[0])["offset"][0] == "0"
    assert _query(deposit_calls[1])["offset"][0] == "1000"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_binance_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.binance'`.

- [ ] **Step 3: Implement `app/adapters/binance.py`**

```python
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.adapters.binance_auth import build_signed_params
from app.config import TradingPairConfig
from app.schemas import NormalizedTransaction

API_URL = "https://api.binance.com"
PAGE_LIMIT = 1000
MAX_RETRIES = 3

DEPOSIT_SUCCESS_STATUS = "1"
WITHDRAWAL_SUCCESS_STATUS = "6"

# Binance caps every deposit/withdrawal history query to a 90-day window
# between startTime and endTime - unlike MEXC, which allows an arbitrarily
# long range in a single call. To cover a longer gap, the adapter walks
# consecutive 90-day windows from a start point up to "now".
WINDOW = timedelta(days=90)

# Binance has no "give me everything" mode for deposits/withdrawals: without
# startTime it silently defaults to the last 90 days. For the very first
# sync (since is None) we need a concrete start point. BINANCE_SYNC_START
# (wired in Task 4) lets the user provide their account creation date; if
# they don't, this fallback covers 5 years, a generous upper bound for
# realistic account ages rather than silently missing history.
DEFAULT_SYNC_START_LOOKBACK = timedelta(days=365 * 5)

# Same watermark-safety pattern already proven necessary in Coinbase's and
# MEXC's *final* reviews (see app/adapters/mexc.py's SYNC_LOOKBACK comment):
# fetch_transactions() combines two independent Binance data streams -
# deposits and withdrawals - under one shared sync watermark. A deposit
# still pending (status != DEPOSIT_SUCCESS_STATUS) or a withdrawal still
# processing (status != WITHDRAWAL_SUCCESS_STATUS) is filtered out and never
# persisted; if it completes later, its original insertTime/applyTime can
# already be before a watermark advanced by the *other*, faster stream. We
# widen the effective window start by a trailing safety margin on every
# incremental sync so a late-completing record is re-fetched and picked up.
# Re-seeing an already-persisted transaction is a harmless no-op in sync.py
# (dedup by external_id).
SYNC_LOOKBACK = timedelta(days=7)


class BinanceAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "binance"

    def __init__(
        self,
        account_label: str,
        api_key: str,
        api_secret: str,
        trading_pairs: list[TradingPairConfig],
        sync_start: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        super().__init__(account_label)
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pairs = trading_pairs
        self.sync_start = sync_start
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, path: str, params: dict) -> list:
        response = None
        for attempt in range(MAX_RETRIES):
            signed_params = build_signed_params(params, self.api_secret)
            response = requests.get(
                f"{API_URL}{path}",
                params=signed_params,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10,
            )
            if response.status_code != 429:
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

        response.raise_for_status()
        return response.json()

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        now = self._clock()
        if since is not None:
            effective_since = since - SYNC_LOOKBACK
        else:
            effective_since = self.sync_start or (now - DEFAULT_SYNC_START_LOOKBACK)

        results: list[NormalizedTransaction] = []
        results.extend(self._fetch_deposits(effective_since, now))
        results.extend(self._fetch_withdrawals(effective_since, now))
        results.extend(self._fetch_trades())
        return results

    def _fetch_windowed_records(self, path: str, window_start: datetime, now: datetime) -> list[dict]:
        all_records: list[dict] = []
        cursor = window_start
        while cursor < now:
            window_end = min(cursor + WINDOW, now)
            all_records.extend(self._fetch_window_page(path, cursor, window_end))
            cursor = window_end + timedelta(milliseconds=1)
        return all_records

    def _fetch_window_page(self, path: str, window_start: datetime, window_end: datetime) -> list[dict]:
        records: list[dict] = []
        offset = 0
        start_ms = int(window_start.timestamp() * 1000)
        end_ms = int(window_end.timestamp() * 1000)
        while True:
            batch = self._get(path, {"startTime": start_ms, "endTime": end_ms, "offset": offset, "limit": PAGE_LIMIT})
            records.extend(batch)
            if len(batch) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return records

    def _fetch_deposits(self, effective_since: datetime, now: datetime) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_windowed_records("/sapi/v1/capital/deposit/hisrec", effective_since, now):
            if str(record.get("status")) != DEPOSIT_SUCCESS_STATUS:
                continue
            timestamp = datetime.fromtimestamp(int(record["insertTime"]) / 1000, tz=timezone.utc)
            if timestamp <= effective_since:
                continue
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in",
                    asset=record["coin"],
                    amount=Decimal(str(record["amount"])),
                    external_id=f"deposit-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results

    def _fetch_withdrawals(self, effective_since: datetime, now: datetime) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_windowed_records("/sapi/v1/capital/withdraw/history", effective_since, now):
            if str(record.get("status")) != WITHDRAWAL_SUCCESS_STATUS:
                continue
            timestamp = datetime.fromtimestamp(int(record["applyTime"]) / 1000, tz=timezone.utc)
            if timestamp <= effective_since:
                continue
            fee_raw = record.get("transactionFee")
            fee_amount = Decimal(str(fee_raw)) if fee_raw and Decimal(str(fee_raw)) != 0 else None
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out",
                    asset=record["coin"],
                    amount=Decimal(str(record["amount"])),
                    fee_amount=fee_amount,
                    fee_asset=record["coin"] if fee_amount is not None else None,
                    external_id=f"withdrawal-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results

    def _fetch_trades(self) -> list[NormalizedTransaction]:
        return []
```

**Note:** `_fetch_trades` is a stub returning `[]` in this task — Task 3 implements it. `trading_pairs` is accepted by the constructor but not yet used. Keeping the constructor's final shape from this task onward means Task 3 only needs to fill in one method, not change the adapter's public interface.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_binance_adapter.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/binance.py KryptoWalletDashboard/backend/tests/test_binance_adapter.py
git commit -m "feat: Binance adapter for deposits and withdrawals with 90-day windowed pagination"
```

---

### Task 3: `BinanceAdapter` — Trades (unbounded `fromId` pagination per configured pair)

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/adapters/binance.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_binance_adapter.py`

**Data source:** `GET /api/v3/myTrades` — **mandatory** `symbol` param, one call (or several, paginated) per configured trading pair. Fields: `id`, `symbol`, `price`, `qty` (base asset amount), `quoteQty` (quote asset amount), `commission`, `commissionAsset`, `time` (ms epoch), `isBuyer` (bool). Pagination via `fromId` (trade ID cursor) has **no time-window restriction**, unlike the `startTime`/`endTime` query mode (capped at 24h, not used here) — so the full trade history is always reachable.

- [ ] **Step 1: Write the failing tests**

Append to `KryptoWalletDashboard/backend/tests/test_binance_adapter.py`:
```python
from app.config import TradingPairConfig


def _trade(trade_id, price, qty, quote_qty, is_buyer, time_ms, commission="0", commission_asset="BTC"):
    return {
        "id": trade_id,
        "price": str(price),
        "qty": str(qty),
        "quoteQty": str(quote_qty),
        "commission": str(commission),
        "commissionAsset": commission_asset,
        "time": time_ms,
        "isBuyer": is_buyer,
    }


BTC_USDT = TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")


@responses.activate
def test_buy_trade_receives_base_asset_gives_up_quote_asset():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get(
        "/api/v3/myTrades",
        [_trade(1, "50000", "0.01", "500", True, _ms(NOW), commission="0.00001", commission_asset="BTC")],
    )

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1
    tx = trades[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.01")
    assert tx.counter_asset == "USDT"
    assert tx.counter_amount == Decimal("500")
    assert tx.fee_amount == Decimal("0.00001")
    assert tx.fee_asset == "BTC"
    assert tx.external_id == "trade-BTCUSDT-1"


@responses.activate
def test_sell_trade_receives_quote_asset_gives_up_base_asset():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get(
        "/api/v3/myTrades",
        [_trade(2, "51000", "0.02", "1020", False, _ms(NOW), commission="1.02", commission_asset="USDT")],
    )

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1
    tx = trades[0]
    assert tx.asset == "USDT"
    assert tx.amount == Decimal("1020")
    assert tx.counter_asset == "BTC"
    assert tx.counter_amount == Decimal("0.02")
    assert tx.fee_amount == Decimal("1.02")
    assert tx.fee_asset == "USDT"


@responses.activate
def test_zero_commission_is_not_recorded():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get("/api/v3/myTrades", [_trade(3, "50000", "0.01", "500", True, _ms(NOW), commission="0")])

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    tx = [r for r in results if r.tx_type == "swap"][0]
    assert tx.fee_amount is None
    assert tx.fee_asset is None


@responses.activate
def test_paginates_trades_via_from_id_until_short_page():
    full_page = [_trade(i, "50000", "0.01", "500", True, _ms(NOW)) for i in range(1000)]
    short_page = [_trade(1000, "50000", "0.01", "500", True, _ms(NOW))]
    responses.add(responses.GET, f"{API_BASE}/api/v3/myTrades", json=full_page, status=200)
    responses.add(responses.GET, f"{API_BASE}/api/v3/myTrades", json=short_page, status=200)
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1001
    trade_calls = [c for c in responses.calls if "/api/v3/myTrades" in c.request.url]
    assert len(trade_calls) == 2
    assert _query(trade_calls[0])["fromId"][0] == "0"
    assert _query(trade_calls[1])["fromId"][0] == "1000"


@responses.activate
def test_fetches_trades_for_each_configured_pair_separately():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    eth_usdt = TradingPairConfig(symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT")
    responses.add(
        responses.GET,
        f"{API_BASE}/api/v3/myTrades",
        json=[_trade("t-btc", "50000", "0.01", "500", True, _ms(NOW))],
        match=[responses.matchers.query_param_matcher({"symbol": "BTCUSDT", "fromId": "0", "limit": "1000"}, strict_match=False)],
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/api/v3/myTrades",
        json=[_trade("t-eth", "3000", "0.5", "1500", True, _ms(NOW))],
        match=[responses.matchers.query_param_matcher({"symbol": "ETHUSDT", "fromId": "0", "limit": "1000"}, strict_match=False)],
    )

    results = _adapter(trading_pairs=[BTC_USDT, eth_usdt], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert {t.external_id for t in trades} == {"trade-BTCUSDT-t-btc", "trade-ETHUSDT-t-eth"}


@responses.activate
def test_no_configured_trading_pairs_means_no_trade_calls():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(trading_pairs=[], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "swap"] == []
    trade_calls = [c for c in responses.calls if "/api/v3/myTrades" in c.request.url]
    assert len(trade_calls) == 0


@responses.activate
def test_trades_are_not_filtered_by_since_full_history_always_refetched():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    old_trade_time = NOW - timedelta(days=400)
    _mock_get("/api/v3/myTrades", [_trade(1, "50000", "0.01", "500", True, _ms(old_trade_time))])

    since = NOW - timedelta(days=1)
    results = _adapter(trading_pairs=[BTC_USDT], now=NOW).fetch_transactions(since)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_binance_adapter.py -v`
Expected: FAIL — the new trade tests fail (`_fetch_trades` currently returns `[]` unconditionally).

- [ ] **Step 3: Implement trade fetching in `app/adapters/binance.py`**

Replace the stub `_fetch_trades` method with:
```python
    def _fetch_trades(self) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for pair in self.trading_pairs:
            results.extend(self._fetch_trades_for_pair(pair))
        return results

    def _fetch_trades_for_pair(self, pair: TradingPairConfig) -> list[NormalizedTransaction]:
        records: list[dict] = []
        from_id = 0
        while True:
            batch = self._get("/api/v3/myTrades", {"symbol": pair.symbol, "fromId": from_id, "limit": PAGE_LIMIT})
            records.extend(batch)
            if len(batch) < PAGE_LIMIT:
                break
            from_id = max(int(r["id"]) for r in batch) + 1

        results = []
        for record in records:
            timestamp = datetime.fromtimestamp(int(record["time"]) / 1000, tz=timezone.utc)
            qty = Decimal(str(record["qty"]))
            quote_qty = Decimal(str(record["quoteQty"]))
            commission_raw = record.get("commission")
            commission = (
                Decimal(str(commission_raw))
                if commission_raw and Decimal(str(commission_raw)) != 0
                else None
            )
            commission_asset = record.get("commissionAsset") if commission is not None else None

            if record["isBuyer"]:
                asset, amount = pair.base_asset, qty
                counter_asset, counter_amount = pair.quote_asset, quote_qty
            else:
                asset, amount = pair.quote_asset, quote_qty
                counter_asset, counter_amount = pair.base_asset, qty

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="swap",
                    asset=asset,
                    amount=amount,
                    counter_asset=counter_asset,
                    counter_amount=counter_amount,
                    fee_amount=commission,
                    fee_asset=commission_asset,
                    external_id=f"trade-{pair.symbol}-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_binance_adapter.py -v`
Expected: PASS (19 tests: 12 from Task 2 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/binance.py KryptoWalletDashboard/backend/tests/test_binance_adapter.py
git commit -m "feat: Binance trade fetching via unbounded fromId pagination"
```

---

### Task 4: Config & Factory Wiring

**Files:**
- Modify: `KryptoWalletDashboard/backend/app/config.py`
- Modify: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_config.py`
- Modify: `KryptoWalletDashboard/backend/tests/test_factory.py`

- [ ] **Step 1: Write the failing test for `BINANCE_SYNC_START` parsing**

Append to `KryptoWalletDashboard/backend/tests/test_config.py`:
```python
def test_parse_sync_start_returns_none_for_empty():
    from app.config import parse_sync_start

    assert parse_sync_start(None) is None
    assert parse_sync_start("") is None


def test_parse_sync_start_parses_iso_date_as_utc_midnight():
    from datetime import datetime, timezone

    from app.config import parse_sync_start

    result = parse_sync_start("2020-01-01")

    assert result == datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_parse_sync_start_returns_none_for_invalid_format():
    from app.config import parse_sync_start

    assert parse_sync_start("not-a-date") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_sync_start'`.

- [ ] **Step 3: Add `parse_sync_start` and the new module constants to `app/config.py`**

Add this function to `KryptoWalletDashboard/backend/app/config.py` (after `parse_trading_pairs`):
```python
def parse_sync_start(env_value: str | None) -> datetime | None:
    """Parse an optional 'YYYY-MM-DD' date string (e.g. Binance account
    creation date) into a UTC midnight datetime. Returns None if unset or
    malformed, in which case the caller falls back to its own default."""
    if not env_value:
        return None
    try:
        return datetime.strptime(env_value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
```

Add the import at the top of `app/config.py` (alongside the existing `dataclass`/`os` imports):
```python
from datetime import datetime, timezone
```

Add alongside the other module-level constants at the bottom of the file:
```python
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TRADING_PAIRS = parse_trading_pairs(os.getenv("BINANCE_TRADING_PAIRS"))
BINANCE_SYNC_START = parse_sync_start(os.getenv("BINANCE_SYNC_START"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS (all tests in the file, including the 3 new ones).

- [ ] **Step 5: Write the failing test for factory wiring**

Append to `KryptoWalletDashboard/backend/tests/test_factory.py`:
```python
def test_binance_adapter_is_added_when_configured(monkeypatch):
    from app.adapters.binance import BinanceAdapter
    from app.config import TradingPairConfig

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "key")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "secret")
    monkeypatch.setattr(
        config, "BINANCE_TRADING_PAIRS", [TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")]
    )
    monkeypatch.setattr(config, "BINANCE_SYNC_START", None)

    adapters = build_adapters_from_config()

    binance_adapters = [a for a in adapters if isinstance(a, BinanceAdapter)]
    assert len(binance_adapters) == 1
    assert binance_adapters[0].account_label == "binance-main"
    assert binance_adapters[0].trading_pairs[0].symbol == "BTCUSDT"


def test_binance_adapter_is_not_added_when_only_partially_configured(monkeypatch):
    from app.adapters.binance import BinanceAdapter

    monkeypatch.setattr(config, "BITCOIN_WALLETS", [])
    monkeypatch.setattr(config, "ETHEREUM_WALLETS", [])
    monkeypatch.setattr(config, "KRAKEN_API_KEY", "")
    monkeypatch.setattr(config, "KRAKEN_API_SECRET", "")
    monkeypatch.setattr(config, "COINBASE_API_KEY_NAME", "")
    monkeypatch.setattr(config, "COINBASE_API_PRIVATE_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_KEY", "")
    monkeypatch.setattr(config, "MEXC_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_API_KEY", "key")
    monkeypatch.setattr(config, "BINANCE_API_SECRET", "")
    monkeypatch.setattr(config, "BINANCE_TRADING_PAIRS", [])
    monkeypatch.setattr(config, "BINANCE_SYNC_START", None)

    adapters = build_adapters_from_config()

    assert not any(isinstance(a, BinanceAdapter) for a in adapters)
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_factory.py -v`
Expected: FAIL — `BinanceAdapter` import succeeds (Task 2/3 already created it), but `build_adapters_from_config()` never builds one.

- [ ] **Step 7: Wire `BinanceAdapter` into `app/adapters/factory.py`**

Add the import:
```python
from app.adapters.binance import BinanceAdapter
```

Add this block after the existing MEXC block:
```python
    if config.BINANCE_API_KEY and config.BINANCE_API_SECRET:
        adapters.append(
            BinanceAdapter(
                account_label="binance-main",
                api_key=config.BINANCE_API_KEY,
                api_secret=config.BINANCE_API_SECRET,
                trading_pairs=config.BINANCE_TRADING_PAIRS,
                sync_start=config.BINANCE_SYNC_START,
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
git commit -m "feat: wire Binance adapter into config and factory"
```

---

### Task 5: Documentation

**Files:**
- Modify: `KryptoWalletDashboard/backend/.env.example`
- Modify: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Document the new config vars in `.env.example`**

Add to `KryptoWalletDashboard/backend/.env.example` (after the existing MEXC section):
```
# Binance: read-only API key/secret. Deposits/withdrawals sync
# automatically (internally paginated in 90-day windows - a Binance API
# limit, transparent to you). Trades require manually listing which pairs
# to track (Binance has no "all trades" endpoint - symbol is mandatory
# per call), format SYMBOL:BASE:QUOTE, comma-separated. Unlike MEXC,
# Binance's trade history has no 30-day limit - the full history is
# always retrievable.
BINANCE_API_KEY=your-read-only-binance-key
BINANCE_API_SECRET=your-read-only-binance-secret
BINANCE_TRADING_PAIRS=BTCUSDT:BTC:USDT,ETHUSDT:ETH:USDT
# Optional: seeds the very first deposit/withdrawal sync's start date
# (e.g. your Binance account creation date, YYYY-MM-DD). Binance has no
# "give me everything" mode for deposits/withdrawals - without this,
# the first sync falls back to covering the last 5 years.
BINANCE_SYNC_START=2020-01-01
```

- [ ] **Step 2: Document Binance setup in `README.md`**

Add a new subsection to `KryptoWalletDashboard/backend/README.md`, near the existing "MEXC" section:
```markdown
## Binance

Zusätzlich zu Bitcoin/EVM-Chains/Kraken/Coinbase/MEXC wird dein Binance-
Account mitsynchronisiert, sobald `BINANCE_API_KEY` und
`BINANCE_API_SECRET` gesetzt sind. Ein-/Auszahlungen werden automatisch
erfasst - keine Konfiguration nötig. Binance erlaubt pro Abfrage nur ein
90-Tage-Fenster; das Tool paginiert das intern automatisch, du merkst
davon nichts.

**Erster Sync:** Ohne Zeitangabe liefert Binance bei Ein-/Auszahlungen
nur die letzten 90 Tage. Setze optional `BINANCE_SYNC_START` (Format
`YYYY-MM-DD`, z.B. dein Konto-Erstellungsdatum) als Startpunkt für den
allerersten Sync. Ohne diese Angabe werden die letzten 5 Jahre
abgedeckt.

**Trades brauchen manuelle Konfiguration:** wie bei MEXC bietet Binance
keinen "alle Trades"-Endpunkt - pro Abfrage muss ein konkretes
Handelspaar angegeben werden. Trage in `BINANCE_TRADING_PAIRS` jedes
Paar ein, das du handelst (Format `SYMBOL:BASE:QUOTE`, z.B.
`BTCUSDT:BTC:USDT`). Ohne konfigurierte Paare werden nur
Ein-/Auszahlungen erfasst, keine Trades.

**Kein 30-Tage-Limit bei Trades:** anders als bei MEXC ist bei Binance
die komplette Handelshistorie über die API abrufbar - kein monatlicher
Zwangs-Sync nötig, um Trades nicht zu verpassen.
```

- [ ] **Step 3: Commit**

```bash
git add KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/README.md
git commit -m "docs: document Binance setup, 90-day windowing, and BINANCE_SYNC_START"
```

---

## Self-Review Notes

- **Spec coverage:** HMAC signing (Task 1), deposits/withdrawals with 90-day-windowed pagination, status filtering, and the `SYNC_LOOKBACK` watermark-safety pattern built in from the start (Task 2), trades via unbounded `fromId` pagination per configured pair with buy/sell direction via `isBuyer` (Task 3), config/factory wiring including the new `BINANCE_SYNC_START` (Task 4), documentation covering all Binance-specific differences from MEXC (Task 5). Matches the design doc's scope exactly.
- **Placeholder scan:** no TBD/TODO. The "API research caveat" is a deliberate, explicit, well-specified constraint (not missing design work) — same pattern already accepted in prior plans.
- **Type/signature consistency:** `BinanceAdapter.__init__(account_label, api_key, api_secret, trading_pairs, sync_start=None, clock=None)` (Task 2) is unchanged through Task 3 and matches exactly how `factory.py` constructs it (Task 4, minus `clock` which production code never passes). `TradingPairConfig(symbol, base_asset, quote_asset)` (reused from `app/config.py`, added in Plan 2b-2) has consistent field names used identically in `binance.py`'s `_fetch_trades_for_pair` (`pair.symbol`, `pair.base_asset`, `pair.quote_asset`) — same as MEXC. `_fetch_windowed_records(path, window_start, now)` / `_fetch_window_page(path, window_start, window_end)` (Task 2) are reused unchanged by both `_fetch_deposits` and `_fetch_withdrawals` — no duplicated pagination logic. `parse_trading_pairs`/`TradingPairConfig` are reused from Plan 2b-2 without modification — confirmed no naming drift (`app/config.py` already defines both at the point this plan starts).
