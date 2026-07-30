from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.bitcoin import BitcoinAdapter

ADDRESS = "bc1qexampleaddress"


def _tx(txid, block_time, vin, vout):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": block_time},
        "vin": vin,
        "vout": vout,
    }


@responses.activate
def test_incoming_transaction_is_transfer_in():
    incoming = _tx(
        "tx-in",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[incoming],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("100000") / Decimal(10**8)
    assert tx.fee_amount is None
    assert tx.external_id == "tx-in"
    assert tx.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)


@responses.activate
def test_outgoing_transaction_is_transfer_out_with_fee():
    outgoing = _tx(
        "tx-out",
        1700000100,
        vin=[{"prevout": {"scriptpubkey_address": ADDRESS, "value": 200000}}],
        vout=[
            {"scriptpubkey_address": "someone-else", "value": 150000},
            {"scriptpubkey_address": ADDRESS, "value": 40000},
        ],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[outgoing],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    # net change for our address: -200000 (spent) + 40000 (change back) = -160000 sats
    assert tx.amount == Decimal("160000") / Decimal(10**8)
    assert tx.fee_amount == Decimal("10000") / Decimal(10**8)
    assert tx.fee_asset == "BTC"


@responses.activate
def test_unconfirmed_transaction_is_skipped():
    unconfirmed = {
        "txid": "tx-pending",
        "status": {"confirmed": False},
        "vin": [{"prevout": {"scriptpubkey_address": "someone-else", "value": 1000}}],
        "vout": [{"scriptpubkey_address": ADDRESS, "value": 500}],
    }
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[unconfirmed],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_transactions():
    older = _tx(
        "tx-old",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    newer = _tx(
        "tx-new",
        1700001000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[older, newer],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["tx-new"]
