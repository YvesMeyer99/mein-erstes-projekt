import json

import responses

from app.adapters.solana import SolanaAdapter

ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
API_URL = "https://api.mainnet-beta.solana.com"


def _rpc_result(result):
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def _sig(signature, block_time, err=None):
    return {
        "signature": signature,
        "slot": 1,
        "err": err,
        "blockTime": block_time,
        "memo": None,
        "confirmationStatus": "finalized",
    }


def _mock_rpc(result):
    responses.add(responses.POST, API_URL, json=_rpc_result(result), status=200)


def _rpc_calls():
    calls = []
    for call in responses.calls:
        body = json.loads(call.request.body)
        calls.append((body["method"], body["params"]))
    return calls


def _minimal_tx():
    return {
        "transaction": {"message": {"accountKeys": [ADDRESS]}},
        "meta": {
            "preBalances": [1000],
            "postBalances": [1000],
            "fee": 0,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


@responses.activate
def test_fetches_signatures_and_calls_gettransaction_for_each_surviving_candidate():
    _mock_rpc([_sig("sig1", 1700000000), _sig("sig2", 1700000100)])
    _mock_rpc(_minimal_tx())
    _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    methods = [m for m, _ in _rpc_calls()]
    assert methods == ["getSignaturesForAddress", "getTransaction", "getTransaction"]


@responses.activate
def test_failed_transactions_are_skipped_without_calling_gettransaction():
    _mock_rpc(
        [
            _sig("sig-ok", 1700000000),
            _sig("sig-failed", 1700000100, err={"InstructionError": [0, "Foo"]}),
        ]
    )
    _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    get_tx_calls = [c for c in _rpc_calls() if c[0] == "getTransaction"]
    assert len(get_tx_calls) == 1
    assert get_tx_calls[0][1][0] == "sig-ok"


@responses.activate
def test_transaction_not_found_is_skipped():
    _mock_rpc([_sig("sig-gone", 1700000000)])
    _mock_rpc(None)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_signatures_without_block_time_are_skipped():
    _mock_rpc([_sig("sig-pending", None)])

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    assert [c[0] for c in _rpc_calls()] == ["getSignaturesForAddress"]


@responses.activate
def test_since_filters_out_older_signatures_before_fetching_transactions():
    from datetime import datetime, timezone

    _mock_rpc([_sig("sig-old", 1700000000), _sig("sig-new", 1700001000)])
    _mock_rpc(_minimal_tx())

    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(since)

    get_tx_calls = [c for c in _rpc_calls() if c[0] == "getTransaction"]
    assert len(get_tx_calls) == 1
    assert get_tx_calls[0][1][0] == "sig-new"


@responses.activate
def test_paginates_through_signatures_until_short_page():
    full_page = [_sig(f"sig-{i}", 1700000000 + i) for i in range(1000)]
    short_page = [_sig("sig-last", 1700002000)]
    _mock_rpc(full_page)
    _mock_rpc(short_page)
    for _ in range(1001):
        _mock_rpc(_minimal_tx())

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    adapter.fetch_transactions(None)

    sig_calls = [c for c in _rpc_calls() if c[0] == "getSignaturesForAddress"]
    assert len(sig_calls) == 2
    assert sig_calls[1][1][1]["before"] == "sig-999"


from decimal import Decimal

OTHER = "11111111111111111111111111111111111111111"


def _tx(account_keys, pre_balances, post_balances, fee=5000):
    return {
        "transaction": {"message": {"accountKeys": account_keys}},
        "meta": {
            "preBalances": pre_balances,
            "postBalances": post_balances,
            "fee": fee,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


@responses.activate
def test_incoming_sol_transfer_is_transfer_in():
    _mock_rpc([_sig("sig-in", 1700000000)])
    _mock_rpc(
        _tx([OTHER, ADDRESS], pre_balances=[2000000000, 1000000000], post_balances=[1000000000, 2000000000])
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "SOL"
    assert tx.amount == Decimal("1000000000") / Decimal(10**9)
    assert tx.fee_amount is None
    assert tx.fee_included_in_amount is False
    assert tx.external_id == "sig-in-native"


@responses.activate
def test_outgoing_sol_transfer_as_fee_payer_includes_fee():
    _mock_rpc([_sig("sig-out", 1700000100)])
    # ADDRESS is accountKeys[0] -> the fee payer. Sent 0.5 SOL, paid a
    # 5000-lamport fee; both are already reflected in the balance delta.
    _mock_rpc(
        _tx(
            [ADDRESS, OTHER],
            pre_balances=[2000000000, 0],
            post_balances=[1499995000, 500000000],
            fee=5000,
        )
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("500005000") / Decimal(10**9)
    assert tx.fee_amount == Decimal("5000") / Decimal(10**9)
    assert tx.fee_asset == "SOL"
    # `amount` already includes the fee (it's the fee payer's raw balance
    # delta) -- app.portfolio.compute_portfolio must not subtract
    # fee_amount a second time for this transaction.
    assert tx.fee_included_in_amount is True


@responses.activate
def test_outgoing_transfer_not_as_fee_payer_has_no_fee_attributed():
    _mock_rpc([_sig("sig-out2", 1700000200)])
    # ADDRESS is accountKeys[1], NOT the fee payer.
    _mock_rpc(
        _tx(
            [OTHER, ADDRESS],
            pre_balances=[2000000000, 1000000000],
            post_balances=[1000000000, 500000000],
            fee=5000,
        )
    )

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    assert tx.amount == Decimal("500000000") / Decimal(10**9)
    assert tx.fee_amount is None
    assert tx.fee_included_in_amount is False


@responses.activate
def test_zero_net_change_produces_no_native_entry():
    _mock_rpc([_sig("sig-noop", 1700000300)])
    _mock_rpc(_tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0]))

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_address_not_present_in_account_keys_produces_no_entry():
    _mock_rpc([_sig("sig-weird", 1700000400)])
    _mock_rpc(_tx([OTHER], pre_balances=[1000000000], post_balances=[900000000]))

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@responses.activate
def test_incoming_spl_token_transfer_is_transfer_in():
    _mock_rpc([_sig("sig-token-in", 1700000500)])
    tx = _tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0])
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 2, "mint": USDC_MINT, "owner": ADDRESS, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 2, "mint": USDC_MINT, "owner": ADDRESS, "uiTokenAmount": {"amount": "1500000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    r = results[0]
    assert r.tx_type == "transfer_in"
    assert r.asset == USDC_MINT
    assert r.amount == Decimal("500000") / Decimal(10**6)
    assert r.external_id == f"sig-token-in-{USDC_MINT}"


@responses.activate
def test_newly_created_token_account_with_no_prior_balance_counts_as_transfer_in():
    _mock_rpc([_sig("sig-new-account", 1700000600)])
    tx = _tx([ADDRESS], pre_balances=[1000000000], post_balances=[997000000])  # rent for new token account
    tx["meta"]["preTokenBalances"] = []
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 1, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": ADDRESS, "uiTokenAmount": {"amount": "5000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    token_results = [r for r in results if r.asset != "SOL"]
    assert len(token_results) == 1
    assert token_results[0].tx_type == "transfer_in"
    assert token_results[0].amount == Decimal("5000000") / Decimal(10**6)


@responses.activate
def test_token_balance_for_a_different_owner_is_ignored():
    _mock_rpc([_sig("sig-other-owner", 1700000700)])
    tx = _tx([ADDRESS, OTHER], pre_balances=[1000000000, 0], post_balances=[1000000000, 0])
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 2, "mint": "SomeMint111111111111111111111111111111111", "owner": OTHER, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 2, "mint": "SomeMint111111111111111111111111111111111", "owner": OTHER, "uiTokenAmount": {"amount": "2000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert results == []


@responses.activate
def test_swap_produces_both_a_sol_leg_and_a_token_leg_with_distinct_external_ids():
    _mock_rpc([_sig("sig-swap", 1700000800)])
    token_mint = "TokenMint1111111111111111111111111111111"
    tx = _tx([ADDRESS, OTHER], pre_balances=[2000000000, 0], post_balances=[1000000000, 0], fee=5000)
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 1, "mint": token_mint, "owner": ADDRESS, "uiTokenAmount": {"amount": "0", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = [
        {"accountIndex": 1, "mint": token_mint, "owner": ADDRESS, "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
    ]
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 2
    external_ids = {r.external_id for r in results}
    assert external_ids == {"sig-swap-native", f"sig-swap-{token_mint}"}
    sol_leg = next(r for r in results if r.asset == "SOL")
    token_leg = next(r for r in results if r.asset != "SOL")
    assert sol_leg.tx_type == "transfer_out"
    assert token_leg.tx_type == "transfer_in"


@responses.activate
def test_closed_token_account_counts_as_transfer_out():
    _mock_rpc([_sig("sig-closed-account", 1700000900)])
    tx = _tx([ADDRESS], pre_balances=[1000000000], post_balances=[1002000000])  # rent reclaimed
    tx["meta"]["preTokenBalances"] = [
        {"accountIndex": 1, "mint": "ClosedMint111111111111111111111111111111", "owner": ADDRESS, "uiTokenAmount": {"amount": "3000000", "decimals": 6}},
    ]
    tx["meta"]["postTokenBalances"] = []
    _mock_rpc(tx)

    adapter = SolanaAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    token_results = [r for r in results if r.asset != "SOL"]
    assert len(token_results) == 1
    assert token_results[0].tx_type == "transfer_out"
    assert token_results[0].amount == Decimal("3000000") / Decimal(10**6)
