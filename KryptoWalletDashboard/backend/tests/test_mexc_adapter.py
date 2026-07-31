from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.mexc import MexcAdapter

API_BASE = "https://api.mexc.com"


def _deposit(tx_id, coin, amount, status, insert_time_ms):
    return {
        "amount": str(amount),
        "coin": coin,
        "network": "BSC",
        "status": status,
        "txId": tx_id,
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


def _adapter(trading_pairs=None):
    return MexcAdapter(
        account_label="mexc-main",
        api_key="key",
        api_secret="secret",
        trading_pairs=trading_pairs or [],
    )


@responses.activate
def test_successful_deposit_with_status_5_is_transfer_in():
    _mock_get("/api/v3/capital/deposit/hisrec", [_deposit("tx1", "BTC", "0.5", "5", 1700000000000)])
    _mock_get("/api/v3/capital/withdraw/history", [])

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.5")
    assert tx.source_name == "mexc"
    assert tx.external_id == "deposit-tx1"


@responses.activate
def test_completed_deposit_with_status_12_is_also_transfer_in():
    _mock_get("/api/v3/capital/deposit/hisrec", [_deposit("tx2", "ETH", "1.0", "12", 1700000000000)])
    _mock_get("/api/v3/capital/withdraw/history", [])

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "transfer_in"


@responses.activate
def test_pending_deposit_is_skipped():
    _mock_get("/api/v3/capital/deposit/hisrec", [_deposit("tx3", "BTC", "0.1", "4", 1700000000000)])
    _mock_get("/api/v3/capital/withdraw/history", [])

    assert _adapter().fetch_transactions(None) == []


@responses.activate
def test_successful_withdrawal_is_transfer_out_with_fee():
    _mock_get("/api/v3/capital/deposit/hisrec", [])
    _mock_get(
        "/api/v3/capital/withdraw/history",
        [_withdrawal("w1", "BTC", "0.2", "7", 1700000100000, fee="0.0005")],
    )

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.2")
    assert tx.fee_amount == Decimal("0.0005")
    assert tx.fee_asset == "BTC"
    assert tx.external_id == "withdrawal-w1"


@responses.activate
def test_non_success_withdrawal_status_is_skipped():
    _mock_get("/api/v3/capital/deposit/hisrec", [])
    _mock_get(
        "/api/v3/capital/withdraw/history",
        [_withdrawal("w2", "BTC", "0.1", "4", 1700000100000)],
    )

    assert _adapter().fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_deposits_and_withdrawals():
    _mock_get(
        "/api/v3/capital/deposit/hisrec",
        [
            _deposit("tx-old", "BTC", "0.1", "5", 1700000000000),
            _deposit("tx-new", "BTC", "0.2", "5", 1700100000000),
        ],
    )
    _mock_get("/api/v3/capital/withdraw/history", [])

    since = datetime.fromtimestamp(1700050000, tz=timezone.utc)
    results = _adapter().fetch_transactions(since)

    assert [r.external_id for r in results] == ["deposit-tx-new"]


@responses.activate
def test_paginates_deposits_until_short_page():
    full_page = [
        _deposit(f"tx-{i}", "BTC", "0.01", "5", 1700000000000 + i * 1000)
        for i in range(1000)
    ]
    short_page = [_deposit("tx-last", "BTC", "0.01", "5", 1700002000000)]
    responses.add(responses.GET, f"{API_BASE}/api/v3/capital/deposit/hisrec", json=full_page, status=200)
    responses.add(responses.GET, f"{API_BASE}/api/v3/capital/deposit/hisrec", json=short_page, status=200)
    _mock_get("/api/v3/capital/withdraw/history", [])

    results = _adapter().fetch_transactions(None)

    deposit_results = [r for r in results if r.tx_type == "transfer_in"]
    assert len(deposit_results) == 1001
    deposit_calls = [
        c for c in responses.calls
        if c.request.url.split("?")[0] == f"{API_BASE}/api/v3/capital/deposit/hisrec"
    ]
    assert len(deposit_calls) == 2
