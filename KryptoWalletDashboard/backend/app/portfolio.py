from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

INFLOW_TYPES = {"transfer_in", "staking_reward", "buy"}
OUTFLOW_TYPES = {"transfer_out", "fee", "sell"}


def compute_portfolio(session: Session) -> list[dict]:
    rows = session.execute(select(Transaction)).scalars().all()

    balances: dict[str, Decimal] = {}
    latest_price_per_unit: dict[str, Decimal] = {}

    def add_balance(asset: str, delta: Decimal) -> None:
        balances[asset] = balances.get(asset, Decimal(0)) + delta

    for tx in rows:
        if tx.tx_type in INFLOW_TYPES:
            add_balance(tx.asset, tx.amount)
        elif tx.tx_type in OUTFLOW_TYPES:
            add_balance(tx.asset, -tx.amount)
        elif tx.tx_type == "swap":
            add_balance(tx.asset, tx.amount)
            if tx.counter_asset is not None:
                add_balance(tx.counter_asset, -(tx.counter_amount or Decimal(0)))

        if tx.fee_amount and tx.fee_asset and tx.tx_type != "fee":
            add_balance(tx.fee_asset, -tx.fee_amount)

        if tx.value_chf is not None and tx.amount != 0:
            latest_price_per_unit[tx.asset] = tx.value_chf / tx.amount

    portfolio = []
    for asset, amount in balances.items():
        if amount == 0:
            continue
        price = latest_price_per_unit.get(asset)
        portfolio.append(
            {
                "asset": asset,
                "amount": amount,
                "price_chf": price,
                "value_chf": price * amount if price is not None else None,
            }
        )
    return portfolio
