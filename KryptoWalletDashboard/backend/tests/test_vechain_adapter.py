from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.vechain import VeChainAdapter

ADDR = "0x1234567890123456789012345678901234567890"
OTHER = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
API_URL = "https://sync-mainnet.vechain.org"


def _transfer_entry(sender, recipient, amount_wei, tx_id, clause_index, block_timestamp):
    return {
        "sender": sender,
        "recipient": recipient,
        "amount": hex(amount_wei),
        "meta": {
            "blockID": "0x" + "0" * 64,
            "blockNumber": 1,
            "blockTimestamp": block_timestamp,
            "txID": tx_id,
            "txOrigin": sender,
            "clauseIndex": clause_index,
        },
    }


def _mock_transfer_logs(result):
    responses.add(responses.POST, f"{API_URL}/logs/transfer", json=result, status=200)


def _mock_event_logs(result):
    responses.add(responses.POST, f"{API_URL}/logs/event", json=result, status=200)


@responses.activate
def test_incoming_vet_transfer_is_transfer_in():
    _mock_transfer_logs([_transfer_entry(OTHER, ADDR, 5 * 10**18, "0xtx1", 0, 1700000000)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    r = vet_results[0]
    assert r.tx_type == "transfer_in"
    assert r.amount == Decimal("5")


@responses.activate
def test_outgoing_vet_transfer_is_transfer_out():
    _mock_transfer_logs([_transfer_entry(ADDR, OTHER, 2 * 10**18, "0xtx2", 0, 1700000100)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    assert vet_results[0].tx_type == "transfer_out"
    assert vet_results[0].amount == Decimal("2")


@responses.activate
def test_self_transfer_is_skipped():
    _mock_transfer_logs([_transfer_entry(ADDR, ADDR, 1 * 10**18, "0xtx3", 0, 1700000200)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_zero_amount_transfer_is_skipped():
    _mock_transfer_logs([_transfer_entry(OTHER, ADDR, 0, "0xtx-zero", 0, 1700000250)])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_since_filters_out_older_transfers():
    _mock_transfer_logs(
        [
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-old", 0, 1700000000),
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-new", 0, 1700001000),
        ]
    )
    _mock_event_logs([])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(since)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 1
    assert vet_results[0].timestamp == datetime.fromtimestamp(1700001000, tz=timezone.utc)


@responses.activate
def test_multiple_transfers_in_the_same_clause_get_distinct_external_ids():
    _mock_transfer_logs(
        [
            _transfer_entry(OTHER, ADDR, 1 * 10**18, "0xtx-multi", 0, 1700000400),
            _transfer_entry(ADDR, OTHER, 1 * 10**18, "0xtx-multi", 0, 1700000400),
        ]
    )
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    vet_results = [r for r in results if r.asset == "VET"]
    assert len(vet_results) == 2
    external_ids = {r.external_id for r in vet_results}
    assert len(external_ids) == 2, "both transfers must have distinct external_ids despite sharing tx+clause"


@responses.activate
def test_no_vet_transfers_returns_empty_list():
    _mock_transfer_logs([])
    _mock_event_logs([])

    adapter = VeChainAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
