from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.ethereum import EthereumAdapter

ADDRESS = "0xExampleAddress"


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


@responses.activate
def test_incoming_transaction_is_transfer_in():
    tx = _tx("0xin", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_in"
    assert result.asset == "ETH"
    assert result.amount == Decimal("1")
    assert result.fee_amount is None


@responses.activate
def test_outgoing_transaction_is_transfer_out_with_gas_fee():
    tx = _tx("0xout", 1700000100, ADDRESS, "0xSomeoneElse", 2 * 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
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
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_transactions():
    older = _tx("0xold", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    newer = _tx("0xnew", 1700001000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [older, newer]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["0xnew"]


@responses.activate
def test_no_transactions_found_does_not_raise():
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "0", "message": "No transactions found", "result": []},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_paginates_through_txlist_until_short_page():
    # Page 1: a full page of PAGE_SIZE txs -> must fetch page 2.
    page1 = [
        _tx(f"0xpage1-{i}", 1700000000 + i, "0xSomeoneElse", ADDRESS, 10**18)
        for i in range(EthereumAdapter.PAGE_SIZE)
    ]
    # Page 2: only 1 tx -> short page, pagination must stop here.
    page2 = [_tx("0xpage2-0", 1700100000, "0xSomeoneElse", ADDRESS, 10**18)]

    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": page1},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": page2},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    results = adapter.fetch_transactions(None)

    assert len(results) == EthereumAdapter.PAGE_SIZE + 1
    assert {r.external_id for r in results} == {t["hash"] for t in page1} | {
        t["hash"] for t in page2
    }
    # Only two HTTP calls: page 1 (full), then page 2 (short -> stop).
    assert len(responses.calls) == 2
    assert "page=1" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url
    assert f"offset={EthereumAdapter.PAGE_SIZE}" in responses.calls[0].request.url
