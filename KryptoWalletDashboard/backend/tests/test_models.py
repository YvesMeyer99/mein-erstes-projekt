from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import PriceCache, Transaction


def _make_transaction(**overrides):
    kwargs = dict(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("0.1"),
        external_id="tx123",
        raw_json="{}",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_transaction_can_be_inserted(db_session):
    db_session.add(_make_transaction())
    db_session.commit()
    assert db_session.query(Transaction).count() == 1


def test_duplicate_external_id_for_same_source_and_account_is_rejected(db_session):
    db_session.add(_make_transaction())
    db_session.commit()
    db_session.add(_make_transaction())
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_external_id_allowed_for_different_account(db_session):
    db_session.add(_make_transaction(account_label="main"))
    db_session.commit()
    db_session.add(_make_transaction(account_label="savings"))
    db_session.commit()
    assert db_session.query(Transaction).count() == 2


def test_transaction_amount_round_trips_exactly_for_non_binary_decimal(db_session):
    # Decimal("0.1") has no exact binary floating-point representation.
    # Plain SQLAlchemy Numeric on SQLite lets the NUMERIC type affinity
    # coerce the value into a float on storage, so it previously came back
    # as Decimal("0.100000000000000006"). This must round-trip exactly.
    db_session.add(_make_transaction(amount=Decimal("0.1")))
    db_session.commit()
    db_session.expire_all()

    saved = db_session.query(Transaction).one()
    assert saved.amount == Decimal("0.1")
    assert str(saved.amount) == "0.1"


def test_price_cache_price_chf_round_trips_exactly_for_non_binary_decimal(db_session):
    db_session.add(
        PriceCache(asset="BTC", date=date(2024, 1, 1), price_chf=Decimal("42000.33"))
    )
    db_session.commit()
    db_session.expire_all()

    saved = db_session.query(PriceCache).one()
    assert saved.price_chf == Decimal("42000.33")
    assert str(saved.price_chf) == "42000.33"
