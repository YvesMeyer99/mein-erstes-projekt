from datetime import date
from decimal import Decimal

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceCache

COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "XBT": "bitcoin",
    "ETH": "ethereum",
}


class CoinGeckoPriceClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def get_price_chf(self, asset: str, on_date: date) -> Decimal | None:
        coingecko_id = COINGECKO_ID_MAP.get(asset.upper())
        if coingecko_id is None:
            return None
        response = requests.get(
            f"{self.BASE_URL}/coins/{coingecko_id}/history",
            params={"date": on_date.strftime("%d-%m-%Y"), "localization": "false"},
            timeout=10,
        )
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
        session.commit()
    return price
