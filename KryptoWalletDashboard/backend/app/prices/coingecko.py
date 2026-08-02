import time
from datetime import date
from decimal import Decimal

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assets import normalize_asset
from app.models import PriceCache

# Keyed by canonical symbol (see app.assets.normalize_asset). Source-specific
# codes like Kraken's XBT/ETH2 are intentionally NOT duplicated here: they're
# normalized to BTC/ETH before reaching this map, both at write time in
# app.sync and defensively below via normalize_asset(), so a second entry
# here would just be a second place for the two mappings to drift apart.
COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "MATIC": "matic-network",
    "SOL": "solana",
    "ADA": "cardano",
    "VET": "vechain",
    # No "VTHO" entry: VIP-180 transfers (including VTHO) are stored with
    # `asset` set to the contract address, never the "VTHO" symbol (see
    # app/adapters/vechain.py), so a symbol-keyed map entry would be
    # unreachable dead code. VIP-180 tokens are documented as unpriced
    # in README.md.
}

MAX_RETRIES = 3


class CoinGeckoPriceClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def get_price_chf(self, asset: str, on_date: date) -> Decimal | None:
        coingecko_id = COINGECKO_ID_MAP.get(normalize_asset(asset))
        if coingecko_id is None:
            return None

        response = None
        for attempt in range(MAX_RETRIES):
            response = requests.get(
                f"{self.BASE_URL}/coins/{coingecko_id}/history",
                params={"date": on_date.strftime("%d-%m-%Y"), "localization": "false"},
                timeout=10,
            )
            if response.status_code != 429:
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

        # A 4xx response (other than an exhausted-retry 429) means CoinGecko
        # has no price data for this coin/date combo -- typically a date
        # older than the free tier's ~365-day history window. That's "no
        # data available", not a real failure, so it must not raise and
        # abort the whole sync batch; treat it the same as a 200 response
        # with an empty market_data body (see below): return None. Anything
        # else (a 429 that survived all retries, or a 5xx/network-level
        # problem) is a genuine failure and should still raise via
        # raise_for_status() so it surfaces via last_error and aborts the
        # batch, same as before.
        if response.status_code != 429 and 400 <= response.status_code < 500:
            return None
        response.raise_for_status()
        price = response.json().get("market_data", {}).get("current_price", {}).get("chf")
        return Decimal(str(price)) if price is not None else None

    def get_current_prices_chf(self, assets: list[str]) -> dict[str, Decimal]:
        """Batched *live* price lookup via CoinGecko's /simple/price, for
        today's portfolio valuation -- unlike get_price_chf, which looks up
        a specific historical date for pricing individual transactions.

        Returns a dict keyed by the input asset symbol (not the CoinGecko
        id), containing only assets that both have a COINGECKO_ID_MAP entry
        and a current price in the response. Missing/unmapped assets are
        simply absent, not an error -- same for any request failure (this
        is called from a read-only GET path, where a transient CoinGecko
        outage must fall back to stale prices rather than break the page).
        """
        coingecko_id_by_asset = {
            asset: COINGECKO_ID_MAP[normalize_asset(asset)]
            for asset in assets
            if normalize_asset(asset) in COINGECKO_ID_MAP
        }
        if not coingecko_id_by_asset:
            return {}

        try:
            response = requests.get(
                f"{self.BASE_URL}/simple/price",
                params={"ids": ",".join(sorted(set(coingecko_id_by_asset.values()))), "vs_currencies": "chf"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            return {}

        result = {}
        for asset, coingecko_id in coingecko_id_by_asset.items():
            price = data.get(coingecko_id, {}).get("chf")
            if price is not None:
                result[asset] = Decimal(str(price))
        return result


def get_or_fetch_price_chf(
    session: Session, client: CoinGeckoPriceClient, asset: str, on_date: date
) -> Decimal | None:
    cached = session.execute(
        select(PriceCache).where(PriceCache.asset == asset, PriceCache.date == on_date)
    ).scalar_one_or_none()
    if cached is not None:
        return cached.price_chf

    price = client.get_price_chf(asset, on_date)
    if price is not None:
        session.add(PriceCache(asset=asset, date=on_date, price_chf=price))
        session.flush()
    return price
