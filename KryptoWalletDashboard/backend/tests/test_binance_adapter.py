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
