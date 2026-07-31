import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

COLUMNS = [
    "Datum",
    "Chain/Boerse",
    "Wallet",
    "Typ",
    "Asset",
    "Menge",
    "Kurs CHF",
    "Wert CHF",
    "Gebuehr",
    "Gebuehr Asset",
    "Referenz",
]


def export_csv(
    session: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    source_name: str | None = None,
    tx_type: str | None = None,
    account_label: str | None = None,
) -> str:
    query = select(Transaction).order_by(Transaction.timestamp)
    if start is not None:
        query = query.where(Transaction.timestamp >= start)
    if end is not None:
        query = query.where(Transaction.timestamp <= end)
    if source_name is not None:
        query = query.where(Transaction.source_name == source_name)
    if tx_type is not None:
        query = query.where(Transaction.tx_type == tx_type)
    if account_label is not None:
        query = query.where(Transaction.account_label == account_label)
    rows = session.execute(query).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for tx in rows:
        writer.writerow(
            [
                tx.timestamp.isoformat(),
                tx.source_name,
                tx.account_label,
                tx.tx_type,
                tx.asset,
                str(tx.amount),
                str(tx.price_chf) if tx.price_chf is not None else "",
                str(tx.value_chf) if tx.value_chf is not None else "",
                str(tx.fee_amount) if tx.fee_amount is not None else "",
                tx.fee_asset or "",
                tx.external_id,
            ]
        )
    return output.getvalue()
