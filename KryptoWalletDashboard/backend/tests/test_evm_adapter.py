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


def _empty_token_page():
    return {"status": "0", "message": "No transactions found", "result": []}


@responses.activate
def test_incoming_transaction_is_transfer_in():
    tx = _tx("0xin", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        API_URL,
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

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
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

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
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

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
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

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
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == EvmAdapter.PAGE_SIZE + 1
    assert {r.external_id for r in results} == {t["hash"] for t in page1} | {
        t["hash"] for t in page2
    }
    assert len(responses.calls) == 3
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
    responses.add(responses.GET, API_URL, json=_empty_token_page(), status=200)

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
    assert result.external_id == "0xtoken-in-token-0xusdccontract-0"


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

    assert [r.external_id for r in results] == ["0xnew-token-0xc-0"]


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


@responses.activate
def test_multiple_transfer_logs_same_hash_and_contract_get_distinct_external_ids():
    """A single tx (e.g. a router forwarding tokens through an intermediate
    hop) can emit two separate Transfer log entries for the same
    (hash, contractAddress) pair. Both must survive as distinct results,
    not collide into a single external_id and get deduped away."""
    native_page = {"status": "0", "message": "No transactions found", "result": []}
    leg_one = _token_tx("0xrouter", 1700000000, "0xSomeoneElse", ADDRESS, 1_000_000, "USDC", 6, "0xc")
    leg_two = _token_tx("0xrouter", 1700000000, "0xSomeoneElse", ADDRESS, 2_000_000, "USDC", 6, "0xc")
    token_page = {"status": "1", "message": "OK", "result": [leg_one, leg_two]}
    responses.add(responses.GET, API_URL, json=native_page, status=200)
    responses.add(responses.GET, API_URL, json=token_page, status=200)

    adapter = _ethereum_adapter()
    results = adapter.fetch_transactions(None)

    assert len(results) == 2
    external_ids = [r.external_id for r in results]
    assert external_ids == ["0xrouter-token-0xc-0", "0xrouter-token-0xc-1"]
    assert len(set(external_ids)) == 2
    assert {r.amount for r in results} == {Decimal("1"), Decimal("2")}
