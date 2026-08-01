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
