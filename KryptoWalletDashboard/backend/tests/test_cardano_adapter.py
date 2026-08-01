from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.cardano import CardanoAdapter, normalize_cardano_tx

ADDR = "addr1qxy2lpan99fcnhhwz097erhm0k5m2gce8hcx6ycpwslzcxwgtpsxx4qkumaq"
OTHER = "addr1qother0000000000000000000000000000000000000000000000000000"
CHANGE = "addr1qchange00000000000000000000000000000000000000000000000000"


def _utxo(address, value, asset_list=None):
    return {"payment_addr": {"bech32": address}, "value": str(value), "asset_list": asset_list or []}


def _tx(tx_hash, timestamp, inputs, outputs, fee="170000"):
    return {"tx_hash": tx_hash, "tx_timestamp": timestamp, "fee": fee, "inputs": inputs, "outputs": outputs}


def test_incoming_ada_transfer_is_transfer_in():
    tx = _tx(
        "tx-in",
        1700000000,
        inputs=[_utxo(OTHER, 2000000)],
        outputs=[_utxo(ADDR, 1000000), _utxo(OTHER, 800000)],
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == "ADA"
    assert r.amount == Decimal("1000000") / Decimal(10**6)
    assert r.fee_amount is None
    assert r.external_id == "tx-in-ADA"
    assert r.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_outgoing_ada_transfer_includes_fee():
    tx = _tx(
        "tx-out",
        1700000100,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[_utxo(OTHER, 1830000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("2000000") / Decimal(10**6)
    assert r.fee_amount == Decimal("170000") / Decimal(10**6)
    assert r.fee_asset == "ADA"


def test_change_to_a_different_owned_address_nets_correctly():
    # Spend 2,000,000 lovelace from ADDR: 1,500,000 to OTHER, 330,000 back
    # as change to CHANGE (also ours, e.g. resolved via a stake address),
    # 170,000 fee. True net outflow: 1,500,000 + 170,000 = 1,670,000 --
    # NOT 2,000,000 (which would double-count the change as if it left).
    tx = _tx(
        "tx-change",
        1700000200,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[_utxo(OTHER, 1500000), _utxo(CHANGE, 330000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR, CHANGE}, "main", None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("1670000") / Decimal(10**6)
    assert r.fee_amount == Decimal("170000") / Decimal(10**6)


def test_fully_internal_transfer_with_fee_is_skipped_entirely():
    # Every input AND every output belongs to owned_addresses -- a pure
    # wallet-internal reshuffle. No ADA left the wallet as a whole; only
    # the network fee did, which is not treated as a taxable transfer_out
    # here (same reasoning as app/adapters/bitcoin.py's identical check).
    tx = _tx(
        "tx-internal",
        1700000300,
        inputs=[_utxo(ADDR, 1000000)],
        outputs=[_utxo(CHANGE, 830000)],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR, CHANGE}, "main", None)

    assert results == []


def test_zero_net_change_produces_no_ada_entry():
    tx = _tx("tx-noop", 1700000400, inputs=[_utxo(OTHER, 1000000)], outputs=[_utxo(OTHER, 830000)])

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert results == []


def test_incoming_native_token_transfer_is_transfer_in():
    tx = _tx(
        "tx-token-in",
        1700000500,
        inputs=[_utxo(OTHER, 2000000)],
        outputs=[
            _utxo(
                ADDR,
                1200000,
                asset_list=[{"policy_id": "abcd1234", "asset_name": "484f534b59", "quantity": "500"}],
            ),
            _utxo(OTHER, 700000),
        ],
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    token_results = [r for r in results if r.asset != "ADA"]
    assert len(token_results) == 1
    r = token_results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == "abcd1234484f534b59"
    assert r.amount == Decimal("500")
    assert r.external_id == "tx-token-in-abcd1234484f534b59"


def test_ada_and_token_legs_in_one_tx_get_distinct_external_ids():
    tx = _tx(
        "tx-swap",
        1700000600,
        inputs=[_utxo(ADDR, 2000000)],
        outputs=[
            _utxo(OTHER, 1830000),
            _utxo(ADDR, 0, asset_list=[{"policy_id": "abcd1234", "asset_name": "484f534b59", "quantity": "100"}]),
        ],
        fee="170000",
    )

    results = normalize_cardano_tx(tx, {ADDR}, "main", None)

    assert len(results) == 2
    external_ids = {r.external_id for r in results}
    assert external_ids == {"tx-swap-ADA", "tx-swap-abcd1234484f534b59"}
    ada_leg = next(r for r in results if r.asset == "ADA")
    token_leg = next(r for r in results if r.asset != "ADA")
    assert ada_leg.tx_type == "transfer_out"
    assert token_leg.tx_type == "transfer_in"


def test_since_filters_out_older_transactions():
    tx = _tx("tx-old", 1700000000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = normalize_cardano_tx(tx, {ADDR}, "main", since)

    assert results == []


API_URL = "https://api.koios.rest/api/v1"


def _sig(tx_hash, block_time):
    return {"tx_hash": tx_hash, "block_height": 1, "block_time": block_time}


def _mock_address_txs(result):
    responses.add(responses.POST, f"{API_URL}/address_txs", json=result, status=200)


def _mock_tx_info(result):
    responses.add(responses.POST, f"{API_URL}/tx_info", json=result, status=200)


@responses.activate
def test_cardano_adapter_fetches_and_normalizes_transactions():
    _mock_address_txs([_sig("tx-in", 1700000000)])
    _mock_tx_info(
        [_tx("tx-in", 1700000000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000), _utxo(OTHER, 800000)])]
    )

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "transfer_in"
    assert results[0].amount == Decimal("1000000") / Decimal(10**6)


@responses.activate
def test_cardano_adapter_no_transactions_means_no_tx_info_call():
    _mock_address_txs([])

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
    tx_info_calls = [c for c in responses.calls if c.request.url.endswith("/tx_info")]
    assert len(tx_info_calls) == 0


@responses.activate
def test_cardano_adapter_since_excludes_old_signatures_from_tx_info_call():
    _mock_address_txs([_sig("tx-old", 1700000000), _sig("tx-new", 1700001000)])
    _mock_tx_info(
        [_tx("tx-new", 1700001000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])]
    )

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = CardanoAdapter(account_label="main", address=ADDR)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-new-ADA"]
    tx_info_call = next(c for c in responses.calls if c.request.url.endswith("/tx_info"))
    import json as _json

    sent_hashes = _json.loads(tx_info_call.request.body)["_tx_hashes"]
    assert sent_hashes == ["tx-new"]


@responses.activate
def test_cardano_adapter_paginates_address_txs_until_short_page():
    full_page = [_sig(f"tx-{i}", 1700000000 + i) for i in range(1000)]
    short_page = [_sig("tx-last", 1700002000)]
    _mock_address_txs(full_page)
    _mock_address_txs(short_page)
    _mock_tx_info([])

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    adapter.fetch_transactions(None)

    address_txs_calls = [c for c in responses.calls if c.request.url.split("?")[0].endswith("/address_txs")]
    assert len(address_txs_calls) == 2


@responses.activate
def test_cardano_adapter_chunks_tx_info_requests_over_1000_hashes():
    signatures = [_sig(f"tx-{i}", 1700000000 + i) for i in range(1500)]
    # 1500 signatures also exceeds PAGE_LIMIT (1000) for /address_txs itself,
    # so that pagination needs two mocked pages too, not just one.
    _mock_address_txs(signatures[:1000])
    _mock_address_txs(signatures[1000:])
    _mock_tx_info([])
    _mock_tx_info([])

    adapter = CardanoAdapter(account_label="main", address=ADDR)
    adapter.fetch_transactions(None)

    tx_info_calls = [c for c in responses.calls if c.request.url.endswith("/tx_info")]
    assert len(tx_info_calls) == 2
    import json as _json

    first_chunk = _json.loads(tx_info_calls[0].request.body)["_tx_hashes"]
    second_chunk = _json.loads(tx_info_calls[1].request.body)["_tx_hashes"]
    assert len(first_chunk) == 1000
    assert len(second_chunk) == 500


from app.adapters.cardano import CardanoStakeAdapter

STAKE_ADDR = "stake1uxyz0000000000000000000000000000000000000000000000000000"


def _mock_account_addresses(stake_address, addresses):
    responses.add(
        responses.POST,
        f"{API_URL}/account_addresses",
        json=[{"stake_address": stake_address, "addresses": addresses}],
        status=200,
    )


def _mock_account_txs(result):
    responses.add(responses.GET, f"{API_URL}/account_txs", json=result, status=200)


@responses.activate
def test_cardano_stake_adapter_resolves_addresses_and_nets_across_all_of_them():
    _mock_account_addresses(STAKE_ADDR, [ADDR, CHANGE])
    _mock_account_txs([_sig("tx-change", 1700000200)])
    _mock_tx_info(
        [
            _tx(
                "tx-change",
                1700000200,
                inputs=[_utxo(ADDR, 2000000)],
                outputs=[_utxo(OTHER, 1500000), _utxo(CHANGE, 330000)],
                fee="170000",
            )
        ]
    )

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_out"
    assert r.amount == Decimal("1670000") / Decimal(10**6)


@responses.activate
def test_cardano_stake_adapter_internal_transfer_between_resolved_addresses_is_skipped():
    _mock_account_addresses(STAKE_ADDR, [ADDR, CHANGE])
    _mock_account_txs([_sig("tx-internal", 1700000300)])
    _mock_tx_info(
        [_tx("tx-internal", 1700000300, inputs=[_utxo(ADDR, 1000000)], outputs=[_utxo(CHANGE, 830000)], fee="170000")]
    )

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_cardano_stake_adapter_no_transactions_means_no_tx_info_call():
    _mock_account_addresses(STAKE_ADDR, [ADDR])
    _mock_account_txs([])

    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(None)

    assert results == []
    tx_info_calls = [c for c in responses.calls if c.request.url.endswith("/tx_info")]
    assert len(tx_info_calls) == 0


@responses.activate
def test_cardano_stake_adapter_since_excludes_old_transactions():
    _mock_account_addresses(STAKE_ADDR, [ADDR])
    _mock_account_txs([_sig("tx-old", 1700000000), _sig("tx-new", 1700001000)])
    _mock_tx_info([_tx("tx-new", 1700001000, inputs=[_utxo(OTHER, 2000000)], outputs=[_utxo(ADDR, 1000000)])])

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = CardanoStakeAdapter(account_label="atomic", stake_address=STAKE_ADDR)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["tx-new-ADA"]
