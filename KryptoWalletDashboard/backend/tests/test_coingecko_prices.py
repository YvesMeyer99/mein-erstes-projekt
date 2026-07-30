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
