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


def test_fee_included_in_amount_is_not_subtracted_a_second_time(db_session):
    # Regression test: Bitcoin/Cardano/Solana's native-transfer adapters
    # compute `amount` as the transaction's *total* wallet-balance decrease,
    # which already has the fee baked in (see e.g.
    # app.adapters.bitcoin.normalize_bitcoin_tx). Unlike
    # test_fee_reduces_balance_of_fee_asset above (an EVM-style transfer,
    # where `amount` is only the transferred value and the gas fee is a
    # fully independent deduction), subtracting `fee_amount` again here
    # would double-count the fee that's already part of `amount`.
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_out",
            asset="BTC",
            amount=Decimal("0.0016"),
            fee_amount=Decimal("0.0001"),
            fee_asset="BTC",
            fee_included_in_amount=True,
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["BTC"]["amount"] == Decimal("-0.0016")


def test_fee_value_chf_price_source_still_applies_when_fee_included_in_amount(db_session):
    # The fee-asset price derivation (used so a fee paid in an asset with
    # no other priced transaction, e.g. a Cardano transfer's ADA fee, still
    # gets a price_chf) must keep working even when the fee is already
    # folded into `amount` and therefore not separately subtracted from the
    # balance -- these are two independent uses of fee_amount/fee_value_chf.
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_out",
            asset="BTC",
            amount=Decimal("0.0016"),
            price_chf=None,
            value_chf=None,
            fee_amount=Decimal("0.0001"),
            fee_asset="BTC",
            fee_value_chf=Decimal("5"),
            fee_included_in_amount=True,
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["BTC"]["price_chf"] == Decimal("5") / Decimal("0.0001")


class FakePriceClient:
    def __init__(self, prices: dict[str, Decimal]):
        self._prices = prices

    def get_current_prices_chf(self, assets):
        return {asset: price for asset, price in self._prices.items() if asset in assets}


def test_uses_current_price_over_last_transaction_price_when_available(db_session):
    # Regression test for the reported bug: the Uebersicht total used the
    # PRICE FROM THE LAST TRANSACTION for an asset (which can be stale by
    # months if you haven't traded it recently) instead of today's actual
    # market price, silently understating or overstating the total value.
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("2"),
            price_chf=Decimal("50000"),
            value_chf=Decimal("100000"),
        )
    )
    db_session.commit()

    portfolio = {
        row["asset"]: row
        for row in compute_portfolio(db_session, price_client=FakePriceClient({"BTC": Decimal("80000")}))
    }

    assert portfolio["BTC"]["price_chf"] == Decimal("80000")
    assert portfolio["BTC"]["value_chf"] == Decimal("160000")


def test_falls_back_to_last_transaction_price_when_current_price_unavailable(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            price_chf=Decimal("50000"),
            value_chf=Decimal("50000"),
        )
    )
    db_session.commit()

    portfolio = {
        row["asset"]: row for row in compute_portfolio(db_session, price_client=FakePriceClient({}))
    }

    assert portfolio["BTC"]["price_chf"] == Decimal("50000")


def test_no_price_client_keeps_last_transaction_price_behavior(db_session):
    # Backward compatibility: every existing call site/test that doesn't
    # pass a price_client must behave exactly as before this feature.
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            price_chf=Decimal("50000"),
            value_chf=Decimal("50000"),
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}

    assert portfolio["BTC"]["price_chf"] == Decimal("50000")


def test_current_price_only_requested_for_assets_with_nonzero_balance(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", asset="BTC", amount=Decimal("1")))
    db_session.add(_tx(external_id="2", tx_type="transfer_out", asset="BTC", amount=Decimal("1")))
    db_session.commit()

    requested = []

    class RecordingPriceClient:
        def get_current_prices_chf(self, assets):
            requested.extend(assets)
            return {}

    compute_portfolio(db_session, price_client=RecordingPriceClient())

    assert requested == []


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


def test_onchain_and_kraken_holdings_of_same_asset_combine_into_one_line(db_session):
    # Regression test for the reported bug: an on-chain Bitcoin wallet and a
    # Kraken account both holding BTC used to show up as two separate
    # portfolio lines, because Kraken's raw ledger code ("XBT") was stored
    # as-is instead of being normalized to "BTC". The fix normalizes
    # asset/counter_asset/fee_asset at write time in app.sync (see
    # test_sync.py's test_sync_normalizes_kraken_asset_codes_to_canonical_symbols),
    # so by the time a Transaction row reaches the DB its asset is already
    # canonical. compute_portfolio() itself deliberately does no defensive
    # re-normalization: app.sync is the only code path that writes
    # Transaction rows (this is a fresh Phase-1 app with no pre-existing,
    # un-normalized data to migrate), so relying solely on write-time
    # normalization is sufficient and keeps compute_portfolio() simple. This
    # test proves that's enough: two rows with the canonical asset "BTC" --
    # one representing what the Bitcoin adapter would write, one
    # representing what Kraken's "XBT" now normalizes to -- combine into a
    # single portfolio entry.
    db_session.add(
        _tx(
            external_id="onchain-1",
            source_name="bitcoin",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("0.5"),
        )
    )
    db_session.add(
        _tx(
            external_id="kraken-1",
            source_name="kraken",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("0.3"),
        )
    )
    db_session.commit()

    portfolio = compute_portfolio(db_session)

    assert len(portfolio) == 1
    assert portfolio[0]["asset"] == "BTC"
    assert portfolio[0]["amount"] == Decimal("0.8")


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
