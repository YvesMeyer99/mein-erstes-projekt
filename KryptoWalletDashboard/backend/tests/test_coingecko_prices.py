from datetime import date
from decimal import Decimal
from unittest.mock import patch

import responses

from app.models import PriceCache
from app.prices.coingecko import CoinGeckoPriceClient, get_or_fetch_price_chf


@responses.activate
def test_client_fetches_historical_price_in_chf():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {"current_price": {"chf": "42000.5"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BTC", date(2024, 1, 15))

    assert price == Decimal("42000.5")
    assert responses.calls[0].request.params["date"] == "15-01-2024"


def test_client_returns_none_for_unknown_asset():
    client = CoinGeckoPriceClient()
    assert client.get_price_chf("NOT-A-COIN", date(2024, 1, 15)) is None


@responses.activate
def test_client_resolves_eth2_via_ethereum_id():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/ethereum/history",
        json={"market_data": {"current_price": {"chf": "2500.0"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("ETH2", date(2024, 1, 15))

    assert price == Decimal("2500.0")
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url.startswith(
        "https://api.coingecko.com/api/v3/coins/ethereum/history"
    )


@responses.activate
@patch("app.prices.coingecko.time.sleep")
def test_client_retries_on_429_then_succeeds(mock_sleep):
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        status=429,
    )
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        status=429,
    )
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {"current_price": {"chf": "42000.5"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BTC", date(2024, 1, 15))

    assert price == Decimal("42000.5")
    assert len(responses.calls) == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


@responses.activate
def test_client_returns_none_on_401_instead_of_raising():
    # CoinGecko's free tier returns a 401 (or 404, depending on the
    # coin/date combo) when historical data isn't available for the
    # requested date -- typically because it's older than the ~365-day
    # window the free tier serves. That must be treated as "no price data",
    # not a hard failure.
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        status=401,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BTC", date(2018, 1, 15))

    assert price is None


@responses.activate
def test_get_or_fetch_price_chf_uses_cache_on_second_call(db_session):
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {"current_price": {"chf": "42000.5"}}},
        status=200,
    )
    client = CoinGeckoPriceClient()

    first = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))
    second = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))

    assert first == Decimal("42000.5")
    assert second == Decimal("42000.5")
    assert len(responses.calls) == 1
    assert db_session.query(PriceCache).count() == 1


@responses.activate
def test_get_or_fetch_price_chf_returns_none_and_does_not_cache_on_missing_price(db_session):
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {}},
        status=200,
    )
    client = CoinGeckoPriceClient()

    result = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))

    assert result is None
    assert db_session.query(PriceCache).count() == 0


@responses.activate
def test_client_resolves_bnb_price():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/binancecoin/history",
        json={"market_data": {"current_price": {"chf": "300.0"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BNB", date(2024, 1, 15))

    assert price == Decimal("300.0")


@responses.activate
def test_get_current_prices_chf_batches_multiple_assets_in_one_call():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/simple/price",
        json={"bitcoin": {"chf": "50000"}, "solana": {"chf": "150.5"}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    prices = client.get_current_prices_chf(["BTC", "SOL"])

    assert prices == {"BTC": Decimal("50000"), "SOL": Decimal("150.5")}
    assert len(responses.calls) == 1
    request_ids = responses.calls[0].request.params["ids"]
    assert set(request_ids.split(",")) == {"bitcoin", "solana"}


@responses.activate
def test_get_current_prices_chf_skips_unmapped_assets_without_calling_api():
    prices = CoinGeckoPriceClient().get_current_prices_chf(["NOT-A-COIN"])

    assert prices == {}
    assert len(responses.calls) == 0


@responses.activate
def test_get_current_prices_chf_omits_assets_missing_from_response():
    # CoinGecko simply omits an id from the response body if it has no
    # current price for it (rather than an error) -- that asset must be
    # absent from the result dict too, not raise or default to something.
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/simple/price",
        json={"bitcoin": {"chf": "50000"}},
        status=200,
    )

    prices = CoinGeckoPriceClient().get_current_prices_chf(["BTC", "SOL"])

    assert prices == {"BTC": Decimal("50000")}


@responses.activate
def test_get_current_prices_chf_returns_empty_dict_on_request_failure():
    # Unlike get_price_chf (used at sync time, where a hard failure should
    # surface via the adapter's error report), this is called from the
    # read-only /api/portfolio GET path -- a transient CoinGecko outage
    # must not break the whole page, just fall back to stale prices.
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/simple/price",
        status=500,
    )

    prices = CoinGeckoPriceClient().get_current_prices_chf(["BTC"])

    assert prices == {}


@responses.activate
def test_get_current_prices_chf_returns_empty_dict_on_malformed_json_body():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/simple/price",
        body="<html>not json</html>",
        status=200,
    )

    prices = CoinGeckoPriceClient().get_current_prices_chf(["BTC"])

    assert prices == {}


def test_get_current_prices_chf_returns_empty_dict_for_empty_input():
    prices = CoinGeckoPriceClient().get_current_prices_chf([])

    assert prices == {}


@responses.activate
def test_client_resolves_matic_price():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/matic-network/history",
        json={"market_data": {"current_price": {"chf": "0.75"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("MATIC", date(2024, 1, 15))

    assert price == Decimal("0.75")
