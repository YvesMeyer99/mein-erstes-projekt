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
    external_id: str
    raw_json: str


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
