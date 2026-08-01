import responses

from app.adapters.bitcoin_gap_scan import discover_used_addresses
from app.adapters.bitcoin_hd import derive_address

# Same well-known, public BIP32 test vector used in test_bitcoin_hd.py.
TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"

API_BASE = "https://blockstream.info/api"


def _mock_address_stats(address, tx_count, mempool_count=0):
    responses.add(
        responses.GET,
        f"{API_BASE}/address/{address}",
        json={
            "chain_stats": {"tx_count": tx_count},
            "mempool_stats": {"tx_count": mempool_count},
        },
        status=200,
    )


@responses.activate
def test_stops_a_chain_after_20_consecutive_unused_addresses():
    # 3 used addresses on the receive chain, then 20 unused -> scan stops,
    # address index 23 (the 21st unused in a row) is never queried.
    for i in range(3):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=1)
    for i in range(3, 23):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    # Change chain: nothing used at all -> scan stops after 20 unused, index 0.
    for i in range(20):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    expected_used = {derive_address(TEST_XPUB, chain=0, index=i) for i in range(3)}
    assert used == expected_used
    # Confirm address index 23 on the receive chain was never queried --
    # the scan must have stopped exactly at the 20-unused-in-a-row boundary.
    queried_addresses = {call.request.url.rsplit("/", 1)[-1] for call in responses.calls}
    assert derive_address(TEST_XPUB, chain=0, index=23) not in queried_addresses


@responses.activate
def test_mempool_only_activity_counts_as_used():
    _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=0), tx_count=0, mempool_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    for i in range(20):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    assert used == {derive_address(TEST_XPUB, chain=0, index=0)}


@responses.activate
def test_both_chains_are_scanned_independently():
    _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=0), tx_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=0, index=i), tx_count=0)
    _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=0), tx_count=1)
    for i in range(1, 21):
        _mock_address_stats(derive_address(TEST_XPUB, chain=1, index=i), tx_count=0)

    used = discover_used_addresses(TEST_XPUB)

    assert used == {
        derive_address(TEST_XPUB, chain=0, index=0),
        derive_address(TEST_XPUB, chain=1, index=0),
    }


@responses.activate
def test_no_usage_at_all_returns_empty_set():
    for chain in (0, 1):
        for i in range(20):
            _mock_address_stats(derive_address(TEST_XPUB, chain=chain, index=i), tx_count=0)

    assert discover_used_addresses(TEST_XPUB) == set()
