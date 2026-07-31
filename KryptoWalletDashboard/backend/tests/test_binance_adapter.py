from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import responses

from app.adapters.binance import BinanceAdapter
from app.config import TradingPairConfig

API_BASE = "https://api.binance.com"
NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _deposit(record_id, coin, amount, status, insert_time_ms):
    return {
        "id": record_id,
        "amount": str(amount),
        "coin": coin,
        "network": "BSC",
        "status": status,
        "txId": f"tx-{record_id}",
        "insertTime": insert_time_ms,
    }


def _withdrawal(record_id, coin, amount, status, apply_time_ms, fee="0"):
    return {
        "id": record_id,
        "coin": coin,
        "amount": str(amount),
        "transactionFee": str(fee),
        "status": status,
        "applyTime": apply_time_ms,
    }


def _mock_get(path, payload):
    responses.add(responses.GET, f"{API_BASE}{path}", json=payload, status=200)


def _query(call):
    return parse_qs(urlparse(call.request.url).query)


def _adapter(trading_pairs=None, sync_start=None, now=NOW):
    return BinanceAdapter(
        account_label="binance-main",
        api_key="key",
        api_secret="secret",
        trading_pairs=trading_pairs or [],
        sync_start=sync_start,
        clock=lambda: now,
    )


def _ms(dt):
    return int(dt.timestamp() * 1000)


@responses.activate
def test_successful_deposit_status_1_is_transfer_in():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [_deposit("d1", "BTC", "0.5", 1, _ms(NOW - timedelta(days=1)))])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    deposits = [r for r in results if r.tx_type == "transfer_in"]
    assert len(deposits) == 1
    tx = deposits[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.5")
    assert tx.source_name == "binance"
    assert tx.external_id == "deposit-d1"


@responses.activate
def test_non_success_deposit_status_is_skipped():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [_deposit("d2", "BTC", "0.1", 0, _ms(NOW - timedelta(days=1)))])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "transfer_in"] == []


@responses.activate
def test_successful_withdrawal_status_6_is_transfer_out_with_fee():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w1", "BTC", "0.2", 6, _ms(NOW - timedelta(days=1)), fee="0.0005")],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    withdrawals = [r for r in results if r.tx_type == "transfer_out"]
    assert len(withdrawals) == 1
    tx = withdrawals[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.2")
    assert tx.fee_amount == Decimal("0.0005")
    assert tx.fee_asset == "BTC"
    assert tx.external_id == "withdrawal-w1"


@responses.activate
def test_non_success_withdrawal_status_is_skipped():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w2", "BTC", "0.1", 0, _ms(NOW - timedelta(days=1)))],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "transfer_out"] == []


@responses.activate
def test_zero_withdrawal_fee_is_not_recorded():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get(
        "/sapi/v1/capital/withdraw/history",
        [_withdrawal("w3", "BTC", "0.1", 6, _ms(NOW - timedelta(days=1)), fee="0")],
    )

    results = _adapter(sync_start=NOW - timedelta(days=10)).fetch_transactions(None)

    tx = [r for r in results if r.tx_type == "transfer_out"][0]
    assert tx.fee_amount is None
    assert tx.fee_asset is None


@responses.activate
def test_first_sync_uses_configured_sync_start_as_window_start():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    sync_start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    _adapter(sync_start=sync_start, now=sync_start + timedelta(days=30)).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 1
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(sync_start)
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(sync_start + timedelta(days=30))


@responses.activate
def test_first_sync_falls_back_to_five_years_when_sync_start_not_configured():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    _adapter(sync_start=None, now=NOW).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    expected_start = _ms(NOW - timedelta(days=365 * 5))
    assert int(_query(deposit_calls[0])["startTime"][0]) == expected_start


@responses.activate
def test_incremental_sync_widens_window_by_seven_day_lookback():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    since = NOW - timedelta(days=10)

    _adapter(now=NOW).fetch_transactions(since)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(since - timedelta(days=7))
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(NOW)


@responses.activate
def test_incremental_sync_excludes_records_at_or_before_effective_since():
    since = NOW - timedelta(days=10)
    effective_since = since - timedelta(days=7)
    _mock_get(
        "/sapi/v1/capital/deposit/hisrec",
        [
            _deposit("d-old", "BTC", "0.1", 1, _ms(effective_since)),
            _deposit("d-new", "BTC", "0.2", 1, _ms(effective_since + timedelta(seconds=1))),
        ],
    )
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(now=NOW).fetch_transactions(since)

    assert [r.external_id for r in results] == ["deposit-d-new"]


@responses.activate
def test_splits_into_multiple_90_day_windows_when_gap_is_large():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    sync_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    now = datetime(2020, 5, 1, tzinfo=timezone.utc)  # 121 days later -> 2 windows

    _adapter(sync_start=sync_start, now=now).fetch_transactions(None)

    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 2
    first_window_end = sync_start + timedelta(days=90)
    assert int(_query(deposit_calls[0])["startTime"][0]) == _ms(sync_start)
    assert int(_query(deposit_calls[0])["endTime"][0]) == _ms(first_window_end)
    assert int(_query(deposit_calls[1])["startTime"][0]) == _ms(first_window_end) + 1
    assert int(_query(deposit_calls[1])["endTime"][0]) == _ms(now)


@responses.activate
def test_paginates_within_a_window_via_offset_until_short_page():
    full_page = [_deposit(f"d-{i}", "BTC", "0.01", 1, _ms(NOW - timedelta(days=1))) for i in range(1000)]
    short_page = [_deposit("d-last", "BTC", "0.01", 1, _ms(NOW - timedelta(days=1)))]
    responses.add(responses.GET, f"{API_BASE}/sapi/v1/capital/deposit/hisrec", json=full_page, status=200)
    responses.add(responses.GET, f"{API_BASE}/sapi/v1/capital/deposit/hisrec", json=short_page, status=200)
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(sync_start=NOW - timedelta(days=10), now=NOW).fetch_transactions(None)

    deposits = [r for r in results if r.tx_type == "transfer_in"]
    assert len(deposits) == 1001
    deposit_calls = [c for c in responses.calls if "/capital/deposit/hisrec" in c.request.url]
    assert len(deposit_calls) == 2
    assert _query(deposit_calls[0])["offset"][0] == "0"
    assert _query(deposit_calls[1])["offset"][0] == "1000"


def _trade(trade_id, price, qty, quote_qty, is_buyer, time_ms, commission="0", commission_asset="BTC"):
    return {
        "id": trade_id,
        "price": str(price),
        "qty": str(qty),
        "quoteQty": str(quote_qty),
        "commission": str(commission),
        "commissionAsset": commission_asset,
        "time": time_ms,
        "isBuyer": is_buyer,
    }


BTC_USDT = TradingPairConfig(symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT")


@responses.activate
def test_buy_trade_receives_base_asset_gives_up_quote_asset():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get(
        "/api/v3/myTrades",
        [_trade(1, "50000", "0.01", "500", True, _ms(NOW), commission="0.00001", commission_asset="BTC")],
    )

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1
    tx = trades[0]
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("0.01")
    assert tx.counter_asset == "USDT"
    assert tx.counter_amount == Decimal("500")
    assert tx.fee_amount == Decimal("0.00001")
    assert tx.fee_asset == "BTC"
    assert tx.external_id == "trade-BTCUSDT-1"


@responses.activate
def test_sell_trade_receives_quote_asset_gives_up_base_asset():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get(
        "/api/v3/myTrades",
        [_trade(2, "51000", "0.02", "1020", False, _ms(NOW), commission="1.02", commission_asset="USDT")],
    )

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1
    tx = trades[0]
    assert tx.asset == "USDT"
    assert tx.amount == Decimal("1020")
    assert tx.counter_asset == "BTC"
    assert tx.counter_amount == Decimal("0.02")
    assert tx.fee_amount == Decimal("1.02")
    assert tx.fee_asset == "USDT"


@responses.activate
def test_zero_commission_is_not_recorded():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get("/api/v3/myTrades", [_trade(3, "50000", "0.01", "500", True, _ms(NOW), commission="0")])

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    tx = [r for r in results if r.tx_type == "swap"][0]
    assert tx.fee_amount is None
    assert tx.fee_asset is None


@responses.activate
def test_paginates_trades_via_from_id_until_short_page():
    full_page = [_trade(i, "50000", "0.01", "500", True, _ms(NOW)) for i in range(1000)]
    short_page = [_trade(1000, "50000", "0.01", "500", True, _ms(NOW))]
    responses.add(responses.GET, f"{API_BASE}/api/v3/myTrades", json=full_page, status=200)
    responses.add(responses.GET, f"{API_BASE}/api/v3/myTrades", json=short_page, status=200)
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1001
    trade_calls = [c for c in responses.calls if "/api/v3/myTrades" in c.request.url]
    assert len(trade_calls) == 2
    assert _query(trade_calls[0])["fromId"][0] == "0"
    assert _query(trade_calls[1])["fromId"][0] == "1000"


@responses.activate
def test_fetches_trades_for_each_configured_pair_separately():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    eth_usdt = TradingPairConfig(symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT")
    responses.add(
        responses.GET,
        f"{API_BASE}/api/v3/myTrades",
        json=[_trade("t-btc", "50000", "0.01", "500", True, _ms(NOW))],
        match=[responses.matchers.query_param_matcher({"symbol": "BTCUSDT", "fromId": "0", "limit": "1000"}, strict_match=False)],
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/api/v3/myTrades",
        json=[_trade("t-eth", "3000", "0.5", "1500", True, _ms(NOW))],
        match=[responses.matchers.query_param_matcher({"symbol": "ETHUSDT", "fromId": "0", "limit": "1000"}, strict_match=False)],
    )

    results = _adapter(trading_pairs=[BTC_USDT, eth_usdt], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    trades = [r for r in results if r.tx_type == "swap"]
    assert {t.external_id for t in trades} == {"trade-BTCUSDT-t-btc", "trade-ETHUSDT-t-eth"}


@responses.activate
def test_no_configured_trading_pairs_means_no_trade_calls():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])

    results = _adapter(trading_pairs=[], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "swap"] == []
    trade_calls = [c for c in responses.calls if "/api/v3/myTrades" in c.request.url]
    assert len(trade_calls) == 0


@responses.activate
def test_trades_are_not_filtered_by_since_full_history_always_refetched():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    old_trade_time = NOW - timedelta(days=400)
    _mock_get("/api/v3/myTrades", [_trade(1, "50000", "0.01", "500", True, _ms(old_trade_time))])

    since = NOW - timedelta(days=1)
    results = _adapter(trading_pairs=[BTC_USDT], now=NOW).fetch_transactions(since)

    trades = [r for r in results if r.tx_type == "swap"]
    assert len(trades) == 1


@responses.activate
def test_no_trades_for_configured_pair_returns_empty_without_error():
    _mock_get("/sapi/v1/capital/deposit/hisrec", [])
    _mock_get("/sapi/v1/capital/withdraw/history", [])
    _mock_get("/api/v3/myTrades", [])

    results = _adapter(trading_pairs=[BTC_USDT], sync_start=NOW - timedelta(days=1)).fetch_transactions(None)

    assert [r for r in results if r.tx_type == "swap"] == []
