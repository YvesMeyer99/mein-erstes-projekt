from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.bitcoin_hd import derive_address
from app.adapters.bitcoin_xpub import BitcoinXpubAdapter

TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
API_BASE = "https://blockstream.info/api"

RECEIVE_0 = derive_address(TEST_XPUB, chain=0, index=0)
CHANGE_0 = derive_address(TEST_XPUB, chain=1, index=0)


def _tx(txid, block_time, vin, vout):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": block_time},
        "vin": vin,
        "vout": vout,
    }


def _mock_gap_scan(used_on_receive, used_on_change):
    """Mock a gap scan where only index 0 is used on each of the two
    chains (used_on_receive/used_on_change are bools), and indexes 1-20
    are unused, so scanning stops right after the gap limit."""
    for chain, used_first in ((0, used_on_receive), (1, used_on_change)):
        responses.add(
            responses.GET,
            f"{API_BASE}/address/{derive_address(TEST_XPUB, chain, 0)}",
            json={"chain_stats": {"tx_count": 1 if used_first else 0}, "mempool_stats": {"tx_count": 0}},
            status=200,
        )
        for i in range(1, 21):
            responses.add(
                responses.GET,
                f"{API_BASE}/address/{derive_address(TEST_XPUB, chain, i)}",
                json={"chain_stats": {"tx_count": 0}, "mempool_stats": {"tx_count": 0}},
                status=200,
            )


def _mock_txs(address, txs):
    responses.add(responses.GET, f"{API_BASE}/address/{address}/txs", json=txs, status=200)


@responses.activate
def test_reports_incoming_transaction_on_a_discovered_receive_address():
    _mock_gap_scan(used_on_receive=True, used_on_change=False)
    incoming = _tx(
        "tx-in",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    _mock_txs(RECEIVE_0, [incoming])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.amount == Decimal("100000") / Decimal(10**8)
    assert tx.account_label == "ledger"
    assert tx.external_id == "tx-in"


@responses.activate
def test_internal_spend_and_change_to_owned_addresses_nets_to_zero_and_is_skipped():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    # A transaction that spends entirely from our receive address and sends
    # the change entirely back to our change address: no BTC actually left
    # the wallet, so it must NOT appear as a taxable transfer_out/transfer_in
    # pair -- this is the core correctness fix this whole feature is about.
    internal_move = _tx(
        "tx-internal",
        1700000100,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[{"scriptpubkey_address": CHANGE_0, "value": 199000}],  # 1000 sat fee, no external party
    )
    _mock_txs(RECEIVE_0, [internal_move])
    _mock_txs(CHANGE_0, [internal_move])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_spend_with_change_reports_only_the_true_external_outflow():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    # Spend 200000 sats from our receive address: 150000 goes to someone
    # else, 40000 comes back to our own change address, 10000 is fee.
    # True net outflow from the wallet as a whole: 150000 + 10000 = 160000
    # sats -- NOT 200000 (which would double-count the change as if it had
    # left the wallet too).
    spend = _tx(
        "tx-spend",
        1700000200,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[
            {"scriptpubkey_address": "someone-else", "value": 150000},
            {"scriptpubkey_address": CHANGE_0, "value": 40000},
        ],
    )
    _mock_txs(RECEIVE_0, [spend])
    _mock_txs(CHANGE_0, [spend])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("160000") / Decimal(10**8)
    assert tx.fee_amount == Decimal("10000") / Decimal(10**8)


@responses.activate
def test_a_transaction_seen_from_two_owned_addresses_is_only_reported_once():
    _mock_gap_scan(used_on_receive=True, used_on_change=True)
    shared_tx = _tx(
        "tx-shared",
        1700000300,
        vin=[{"prevout": {"scriptpubkey_address": RECEIVE_0, "value": 200000}}],
        vout=[{"scriptpubkey_address": CHANGE_0, "value": 100000}],
    )
    # The same tx shows up when querying either owned address's tx list
    # (as it would in reality, via Blockstream's API) -- must be deduped.
    _mock_txs(RECEIVE_0, [shared_tx])
    _mock_txs(CHANGE_0, [shared_tx])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert len([r for r in results if r.external_id == "tx-shared"]) <= 1


@responses.activate
def test_since_filters_out_older_transactions():
    _mock_gap_scan(used_on_receive=True, used_on_change=False)
    older = _tx(
        "tx-old",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    newer = _tx(
        "tx-new",
        1700001000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": RECEIVE_0, "value": 100000}],
    )
    _mock_txs(RECEIVE_0, [older, newer])

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["tx-new"]


@responses.activate
def test_no_used_addresses_means_no_transactions_and_no_tx_fetch_calls():
    _mock_gap_scan(used_on_receive=False, used_on_change=False)

    adapter = BitcoinXpubAdapter(account_label="ledger", extended_key=TEST_XPUB)
    results = adapter.fetch_transactions(None)

    assert results == []
    txs_calls = [c for c in responses.calls if c.request.url.endswith("/txs")]
    assert len(txs_calls) == 0
