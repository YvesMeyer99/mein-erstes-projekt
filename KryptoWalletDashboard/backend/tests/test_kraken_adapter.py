from decimal import Decimal

import responses

from app.adapters.kraken import KrakenAdapter


def _ledger_response(ledger: dict) -> dict:
    return {"error": [], "result": {"ledger": ledger, "count": len(ledger)}}


@responses.activate
def test_deposit_is_transfer_in():
    ledger = {
        "L1": {
            "refid": "R1",
            "time": 1700000000.0,
            "type": "deposit",
            "asset": "XBT",
            "amount": "0.5000000000",
            "fee": "0.0000000000",
        }
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "XBT"
    assert tx.amount == Decimal("0.5")
    assert tx.external_id == "L1"


@responses.activate
def test_staking_reward_is_mapped():
    ledger = {
        "L2": {
            "refid": "R2",
            "time": 1700000100.0,
            "type": "staking",
            "asset": "ETH2",
            "amount": "0.0100000000",
            "fee": "0.0000000000",
        }
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "staking_reward"
    assert results[0].amount == Decimal("0.01")


@responses.activate
def test_trade_pair_is_merged_into_a_swap():
    ledger = {
        "T1": {
            "refid": "TRADE1",
            "time": 1700000200.0,
            "type": "trade",
            "asset": "ZEUR",
            "amount": "-100.0000000000",
            "fee": "0.2600000000",
        },
        "T2": {
            "refid": "TRADE1",
            "time": 1700000200.0,
            "type": "trade",
            "asset": "XBT",
            "amount": "0.0030000000",
            "fee": "0.0000000000",
        },
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "swap"
    assert tx.asset == "XBT"
    assert tx.amount == Decimal("0.003")
    assert tx.counter_asset == "ZEUR"
    assert tx.counter_amount == Decimal("100")
    assert tx.fee_amount == Decimal("0.26")
    assert tx.fee_asset == "ZEUR"
    assert tx.external_id == "TRADE1"


@responses.activate
def test_since_filters_out_older_entries():
    ledger = {
        "L1": {"refid": "R1", "time": 1700000000.0, "type": "deposit", "asset": "XBT", "amount": "0.1", "fee": "0"},
        "L2": {"refid": "R2", "time": 1700001000.0, "type": "deposit", "asset": "XBT", "amount": "0.2", "fee": "0"},
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    from datetime import datetime, timezone

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["L2"]


@responses.activate
def test_api_error_raises():
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json={"error": ["EAPI:Invalid key"], "result": {}},
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    try:
        adapter.fetch_transactions(None)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "EAPI:Invalid key" in str(exc)
