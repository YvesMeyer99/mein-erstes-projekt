from datetime import datetime, timezone
from decimal import Decimal

from app.models import Transaction
from app.portfolio import compute_portfolio


def _tx(**overrides):
    kwargs = dict(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("1"),
        external_id="id",
        raw_json="{}",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_incoming_and_outgoing_transfers_net_out(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1"), price_chf=Decimal("100"), value_chf=Decimal("100")))
    db_session.add(_tx(external_id="2", tx_type="transfer_out", amount=Decimal("0.4")))
    db_session.commit()

    portfolio = compute_portfolio(db_session)

    assert len(portfolio) == 1
    assert portfolio[0]["asset"] == "BTC"
    assert portfolio[0]["amount"] == Decimal("0.6")
    assert portfolio[0]["price_chf"] == Decimal("100")
    assert portfolio[0]["value_chf"] == Decimal("60")


def test_zero_balance_asset_is_omitted(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1")))
    db_session.add(_tx(external_id="2", tx_type="transfer_out", amount=Decimal("1")))
    db_session.commit()

    assert compute_portfolio(db_session) == []


def test_swap_moves_balance_between_assets(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="swap",
            asset="BTC",
            amount=Decimal("0.01"),
            counter_asset="ZEUR",
            counter_amount=Decimal("500"),
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["BTC"]["amount"] == Decimal("0.01")
    assert portfolio["ZEUR"]["amount"] == Decimal("-500")


def test_fee_reduces_balance_of_fee_asset(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_out",
            asset="ETH",
            amount=Decimal("1"),
            fee_amount=Decimal("0.001"),
            fee_asset="ETH",
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["ETH"]["amount"] == Decimal("-1.001")


def test_missing_price_yields_none_value(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1"), price_chf=None, value_chf=None))
    db_session.commit()

    portfolio = compute_portfolio(db_session)
    assert portfolio[0]["price_chf"] is None
    assert portfolio[0]["value_chf"] is None


def test_latest_price_is_chosen_by_timestamp_not_insertion_order(db_session):
    newer = _tx(
        external_id="newer",
        tx_type="transfer_in",
        amount=Decimal("1"),
        price_chf=Decimal("200"),
        value_chf=Decimal("200"),
        timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    older = _tx(
        external_id="older",
        tx_type="transfer_in",
        amount=Decimal("1"),
        price_chf=Decimal("50"),
        value_chf=Decimal("50"),
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    # Inserted in reverse chronological order: newer row added first, older row added second.
    db_session.add(newer)
    db_session.add(older)
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["BTC"]["price_chf"] == Decimal("200")


def test_fee_value_chf_is_used_as_price_source_for_fee_asset(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_out",
            asset="BTC",
            amount=Decimal("1"),
            price_chf=None,
            value_chf=None,
            fee_amount=Decimal("0.001"),
            fee_asset="ETH",
            fee_value_chf=Decimal("2.5"),
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["ETH"]["price_chf"] == Decimal("2.5") / Decimal("0.001")
