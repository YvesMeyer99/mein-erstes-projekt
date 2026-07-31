import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.csv_export import export_csv
from app.models import Transaction


def _tx(**overrides):
    kwargs = dict(
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("1"),
        price_chf=Decimal("50000"),
        value_chf=Decimal("50000"),
        external_id="id1",
        raw_json="{}",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_export_includes_header_and_all_columns(db_session):
    db_session.add(_tx())
    db_session.commit()

    rows = _rows(export_csv(db_session))

    assert len(rows) == 1
    row = rows[0]
    assert row["Chain/Boerse"] == "bitcoin"
    assert row["Wallet"] == "main"
    assert row["Typ"] == "transfer_in"
    assert row["Asset"] == "BTC"
    assert row["Menge"] == "1"
    assert row["Kurs CHF"] == "50000"
    assert row["Wert CHF"] == "50000"
    assert row["Referenz"] == "id1"


def test_export_filters_by_date_range(db_session):
    db_session.add(_tx(external_id="old", timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc)))
    db_session.add(_tx(external_id="new", timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc)))
    db_session.commit()

    rows = _rows(
        export_csv(
            db_session,
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )
    )

    assert [r["Referenz"] for r in rows] == ["new"]


def test_export_filters_by_source_name_tx_type_and_account_label(db_session):
    db_session.add(_tx(external_id="a", source_name="bitcoin", tx_type="transfer_in", account_label="main"))
    db_session.add(_tx(external_id="b", source_name="ethereum", tx_type="transfer_out", account_label="savings"))
    db_session.commit()

    rows = _rows(export_csv(db_session, source_name="bitcoin"))
    assert [r["Referenz"] for r in rows] == ["a"]

    rows = _rows(export_csv(db_session, tx_type="transfer_out"))
    assert [r["Referenz"] for r in rows] == ["b"]

    rows = _rows(export_csv(db_session, account_label="savings"))
    assert [r["Referenz"] for r in rows] == ["b"]


def test_export_leaves_missing_price_fields_blank(db_session):
    db_session.add(_tx(price_chf=None, value_chf=None))
    db_session.commit()

    rows = _rows(export_csv(db_session))
    assert rows[0]["Kurs CHF"] == ""
    assert rows[0]["Wert CHF"] == ""
