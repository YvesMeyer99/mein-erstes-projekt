from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.schemas import NormalizedTransaction
from app.sync import sync_all


class FakePriceClient:
    def __init__(self, price=Decimal("100")):
        self.price = price

    def get_price_chf(self, asset, on_date):
        return self.price


class FakeAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "fake"

    def __init__(self, account_label, transactions=None, error=None):
        super().__init__(account_label)
        self._transactions = transactions or []
        self._error = error
        self.received_since = "not-called"

    def fetch_transactions(self, since):
        self.received_since = since
        if self._error is not None:
            raise self._error
        return self._transactions


class TzCheckingAdapter(TransactionAdapter):
    """Mimics the real adapters (bitcoin.py, ethereum.py, kraken.py), which
    all compare `since` against their own timezone-aware timestamps, e.g.
    `if since is not None and timestamp <= since`. A naive `since` makes
    that comparison raise TypeError, exactly like it would for a real
    adapter."""

    source_type = "chain"
    source_name = "fake"

    def __init__(self, account_label, transactions=None):
        super().__init__(account_label)
        self._transactions = transactions or []
        self.received_since = "not-called"

    def fetch_transactions(self, since):
        self.received_since = since
        if since is not None:
            datetime(2024, 1, 15, tzinfo=timezone.utc) <= since
        return self._transactions


def _tx(external_id, amount="1", tx_type="transfer_in", asset="FAKE"):
    return NormalizedTransaction(
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_type="chain",
        source_name="fake",
        account_label="main",
        tx_type=tx_type,
        asset=asset,
        amount=Decimal(amount),
        external_id=external_id,
        raw_json="{}",
    )


def test_sync_persists_new_transactions_and_enriches_price(db_session):
    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    reports = sync_all(db_session, [adapter], FakePriceClient(Decimal("100")))

    assert reports == [{"source_name": "fake", "account_label": "main", "status": "ok", "new_transactions": 1}]
    saved = db_session.query(Transaction).one()
    assert saved.external_id == "t1"
    assert saved.price_chf == Decimal("100")
    assert saved.value_chf == Decimal("100")


def test_sync_skips_already_persisted_transactions(db_session):
    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter], FakePriceClient())
    reports = sync_all(db_session, [FakeAdapter("main", transactions=[_tx("t1")])], FakePriceClient())

    assert reports[0]["new_transactions"] == 0
    assert db_session.query(Transaction).count() == 1


def test_sync_uses_last_synced_at_as_since_on_second_run(db_session):
    adapter1 = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter1], FakePriceClient())

    adapter2 = FakeAdapter("main", transactions=[])
    sync_all(db_session, [adapter2], FakePriceClient())

    state = db_session.query(SyncState).one()
    # `received_since` is normalized to timezone-aware before being handed to
    # adapters, while `state.last_synced_at` comes back naive from SQLite's
    # DateTime(timezone=True) round trip -- compare on wall-clock value only.
    assert adapter2.received_since.replace(tzinfo=None) == state.last_synced_at.replace(tzinfo=None)


def test_sync_passes_timezone_aware_since_to_adapter_on_second_run(db_session):
    adapter1 = TzCheckingAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter1], FakePriceClient())

    adapter2 = TzCheckingAdapter("main", transactions=[])
    reports = sync_all(db_session, [adapter2], FakePriceClient())

    assert reports[0]["status"] == "ok"
    assert adapter2.received_since is not None
    assert adapter2.received_since.tzinfo is not None


def test_sync_records_error_and_continues_with_other_adapters(db_session):
    failing = FakeAdapter("broken", error=RuntimeError("API down"))
    working = FakeAdapter("main", transactions=[_tx("t1")])

    reports = sync_all(db_session, [failing, working], FakePriceClient())

    assert reports[0]["status"] == "error"
    assert "API down" in reports[0]["error"]
    assert reports[1]["status"] == "ok"
    assert db_session.query(Transaction).count() == 1

    failing_state = db_session.query(SyncState).filter_by(account_label="broken").one()
    assert failing_state.last_error == "API down"


def test_sync_handles_missing_price_gracefully(db_session):
    class NonePriceClient:
        def get_price_chf(self, asset, on_date):
            return None

    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter], NonePriceClient())

    saved = db_session.query(Transaction).one()
    assert saved.price_chf is None
    assert saved.value_chf is None
