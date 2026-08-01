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
    "VTHO": "vethor-token",
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
