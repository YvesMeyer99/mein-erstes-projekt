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
    "Gegen-Asset",
    "Gegen-Menge",
    "Kurs CHF",
    "Wert CHF",
    "Gebuehr",
    "Gebuehr Asset",
    "Gebuehr CHF",
    "Referenz",
]

# Leading characters that Excel/LibreOffice interpret as "this cell is a
# formula". Untrusted data (e.g. an ERC-20 token symbol chosen by an
# arbitrary contract deployer) can smuggle a formula like
# =HYPERLINK("http://evil.example") into a CSV cell that later gets opened
# in a spreadsheet. Prefixing such values with a single quote forces the
# cell to be treated as plain text.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: object) -> object:
    """Neutralize CSV/spreadsheet formula injection in string cell values.

    Only strings are inspected; non-string values (e.g. already-formatted
    numeric strings are passed in as strings by the caller, but None etc.
    pass through untouched) are returned unchanged.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def _sanitize_row(row: list) -> list:
    return [_sanitize_cell(cell) for cell in row]


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
            _sanitize_row(
                [
                    tx.timestamp.isoformat(),
                    tx.source_name,
                    tx.account_label,
                    tx.tx_type,
                    tx.asset,
                    format(tx.amount, "f"),
                    tx.counter_asset or "",
                    format(tx.counter_amount, "f") if tx.counter_amount is not None else "",
                    format(tx.price_chf, "f") if tx.price_chf is not None else "",
                    format(tx.value_chf, "f") if tx.value_chf is not None else "",
                    format(tx.fee_amount, "f") if tx.fee_amount is not None else "",
                    tx.fee_asset or "",
                    format(tx.fee_value_chf, "f") if tx.fee_value_chf is not None else "",
                    tx.external_id,
                ]
            )
        )
    return output.getvalue()
