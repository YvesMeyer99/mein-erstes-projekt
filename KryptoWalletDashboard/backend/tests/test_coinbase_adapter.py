from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

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
def test_zero_amount_send_or_receive_is_skipped(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-eth", "ETH")])
    _mock_transactions(
        "acc-eth",
        [
            _tx("tx-zero-in", "receive", "0", "ETH", "2024-01-15T09:00:00Z"),
            _tx("tx-zero-out", "send", "-0", "ETH", "2024-01-15T09:30:00Z"),
        ],
    )

    assert _adapter().fetch_transactions(None) == []


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
def test_since_lookback_margin_includes_recently_completed_transaction(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx-late-complete", "buy", "0.1", "BTC", "2024-02-27T00:00:00Z")],
    )

    # `since` is 2024-03-01; the transaction's created_at (2024-02-27) is
    # only 3 days earlier, which a naive `timestamp <= since` filter would
    # exclude. This simulates a transaction that was still "pending" as of
    # the previous sync's watermark and only completed later -- it must be
    # re-fetched thanks to the 7-day lookback margin, or it would be lost
    # forever (see SYNC_LOOKBACK comment in app/adapters/coinbase.py).
    since = datetime(2024, 3, 1, tzinfo=timezone.utc)
    results = _adapter().fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-late-complete"]


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
def test_fiat_accounts_are_skipped_without_fetching_their_transactions(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    _mock_accounts([_account("acc-btc", "BTC"), _account("acc-eur", "EUR")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx-btc", "buy", "0.1", "BTC", "2024-01-15T10:00:00Z")],
    )
    # A transaction is registered for the EUR account's transactions endpoint
    # too, but the assertions below prove that endpoint is never called at
    # all -- the fiat account must be skipped at the account-iteration level
    # in fetch_transactions, before any HTTP request for its transactions is
    # made, not merely filtered out of the results afterward.
    _mock_transactions(
        "acc-eur",
        [_tx("tx-eur", "buy", "-50.00", "EUR", "2024-01-15T10:00:00Z")],
    )

    results = _adapter().fetch_transactions(None)

    assert [r.external_id for r in results] == ["tx-btc"]
    eur_tx_calls = [
        c
        for c in responses.calls
        if c.request.url.split("?")[0] == f"{API_BASE}/v2/accounts/acc-eur/transactions"
    ]
    assert len(eur_tx_calls) == 0


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


@responses.activate
@patch("app.adapters.coinbase.time.sleep")
def test_retries_on_429_then_succeeds(mock_sleep, monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    responses.add(responses.GET, f"{API_BASE}/v2/accounts", status=429)
    responses.add(responses.GET, f"{API_BASE}/v2/accounts", status=429)
    _mock_accounts([_account("acc-btc", "BTC")])
    _mock_transactions(
        "acc-btc",
        [_tx("tx1", "buy", "0.5", "BTC", "2024-01-15T10:00:00Z")],
    )

    results = _adapter().fetch_transactions(None)

    assert len(results) == 1
    assert results[0].external_id == "tx1"
    account_calls = [c for c in responses.calls if c.request.url.split("?")[0] == f"{API_BASE}/v2/accounts"]
    assert len(account_calls) == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


@responses.activate
def test_persistent_http_error_raises(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.coinbase.build_coinbase_jwt", lambda *a, **k: "fake-jwt"
    )
    responses.add(responses.GET, f"{API_BASE}/v2/accounts", status=401)

    try:
        _adapter().fetch_transactions(None)
        assert False, "expected an exception to be raised"
    except Exception as exc:
        assert "401" in str(exc)
