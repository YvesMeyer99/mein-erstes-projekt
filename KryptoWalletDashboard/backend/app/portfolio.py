from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

INFLOW_TYPES = {"transfer_in", "staking_reward", "buy"}
OUTFLOW_TYPES = {"transfer_out", "fee", "sell"}


def compute_portfolio(session: Session, price_client=None) -> list[dict]:
    rows = session.execute(select(Transaction).order_by(Transaction.timestamp)).scalars().all()

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

        # Some adapters (Bitcoin/Cardano/Solana native transfers) compute
        # `amount` as the transaction's total wallet-balance decrease, which
        # already has the fee baked in -- subtracting fee_amount again here
        # would double-count it. Only adapters where `amount` and
        # `fee_amount` are independent figures (EVM gas, exchange ledger
        # fees, ...) need this separate deduction.
        if tx.fee_amount and tx.fee_asset and tx.tx_type != "fee" and not tx.fee_included_in_amount:
            add_balance(tx.fee_asset, -tx.fee_amount)

        if tx.value_chf is not None and tx.amount != 0:
            latest_price_per_unit[tx.asset] = tx.value_chf / tx.amount

        if tx.fee_value_chf is not None and tx.fee_amount and tx.fee_asset:
            latest_price_per_unit[tx.fee_asset] = tx.fee_value_chf / tx.fee_amount

    # A negative balance for an asset is expected/valid output here: it means
    # more of that asset was spent (e.g. on fees) than was ever recorded as
    # received, which usually signals an incomplete sync history for that
    # asset rather than a bug in this calculation.
    held_assets = [asset for asset, amount in balances.items() if amount != 0]

    # Without this, the reported total value used whatever price was
    # recorded on that asset's LAST transaction -- which can be months
    # stale if you haven't traded it recently, silently mis-stating today's
    # actual portfolio value. price_client is optional (None keeps the old
    # last-transaction-price behavior, e.g. for callers that can't reach
    # the network) and any asset it doesn't return a price for -- no
    # COINGECKO_ID_MAP entry, or a transient API failure -- falls back to
    # the same last-transaction price as before.
    current_prices: dict[str, Decimal] = {}
    if price_client is not None and held_assets:
        current_prices = price_client.get_current_prices_chf(held_assets)

    portfolio = []
    for asset, amount in balances.items():
        if amount == 0:
            continue
        price = current_prices.get(asset, latest_price_per_unit.get(asset))
        portfolio.append(
            {
                "asset": asset,
                "amount": amount,
                "price_chf": price,
                "value_chf": price * amount if price is not None else None,
            }
        )
    return portfolio
