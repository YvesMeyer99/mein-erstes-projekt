from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Transaction


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
