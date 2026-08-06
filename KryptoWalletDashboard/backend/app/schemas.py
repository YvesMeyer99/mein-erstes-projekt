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


class ConfigUpdateRequest(BaseModel):
    """extra="forbid" makes an unexpected top-level key (e.g. the OLD
    pre-this-task POST /api/config body shape, a bare {"FIELD": "value"}
    dict) a 422 validation error instead of being silently accepted and
    defaulting values/sections to {} -- which would otherwise report
    200 {"status": "ok"} while writing nothing at all."""

    model_config = {"extra": "forbid"}

    values: dict[str, str] = {}
    sections: dict[str, bool] = {}
