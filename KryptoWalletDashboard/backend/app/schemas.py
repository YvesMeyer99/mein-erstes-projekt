from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class NormalizedTransaction(BaseModel):
    timestamp: datetime
    source_type: str
    source_name: str
    account_label: str
    tx_type: str
    asset: str
    amount: Decimal
    counter_asset: str | None = None
    counter_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    fee_asset: str | None = None
    # True when `amount` is the total wallet-balance decrease and already
    # has `fee_amount` baked in (Bitcoin/Cardano/Solana native transfers,
    # where the on-chain balance change inherently includes the fee).
    # False (the default) when `amount` and `fee_amount` are independent
    # figures that both reduce the balance separately (EVM gas, Kraken
    # ledger fees, ...). See app.portfolio.compute_portfolio.
    fee_included_in_amount: bool = False
    external_id: str
    raw_json: str


class PortfolioEntryOut(BaseModel):
    asset: str
    amount: Decimal
    price_chf: Decimal | None
    value_chf: Decimal | None


class TransactionOut(BaseModel):
    id: int
    timestamp: datetime
    source_type: str
    source_name: str
    account_label: str
    tx_type: str
    asset: str
    amount: Decimal
    counter_asset: str | None
    counter_amount: Decimal | None
    price_chf: Decimal | None
    value_chf: Decimal | None
    fee_amount: Decimal | None
    fee_asset: str | None
    external_id: str

    model_config = {"from_attributes": True}


class AccountRef(BaseModel):
    source_name: str
    account_label: str


class DeleteAccountsRequest(BaseModel):
    accounts: list[AccountRef]
