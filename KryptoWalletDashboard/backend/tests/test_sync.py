from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.prices.coingecko import CoinGeckoPriceClient
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


def _tx(external_id, amount="1", tx_type="transfer_in", asset="FAKE", fee_amount=None, fee_asset=None):
    return NormalizedTransaction(
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_type="chain",
        source_name="fake",
        account_label="main",
        tx_type=tx_type,
        asset=asset,
        amount=Decimal(amount),
        fee_amount=Decimal(fee_amount) if fee_amount is not None else None,
        fee_asset=fee_asset,
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


def test_sync_enriches_fee_price_when_fee_amount_and_asset_are_present(db_session):
    # 0.5 is exactly representable in binary floating point, avoiding
    # SQLite's Numeric-as-float round-trip drift (e.g. Decimal("0.1") comes
    # back as Decimal("0.100000000000000006")) so the assertion below can
    # use an exact equality check.
    adapter = FakeAdapter(
        "main", transactions=[_tx("t1", fee_amount="0.5", fee_asset="FAKE")]
    )
    sync_all(db_session, [adapter], FakePriceClient(Decimal("100")))

    saved = db_session.query(Transaction).one()
    assert saved.fee_amount == Decimal("0.5")
    assert saved.fee_asset == "FAKE"
    assert saved.fee_value_chf == Decimal("100") * Decimal("0.5")


def test_sync_preserves_case_of_long_case_sensitive_asset_identifiers(db_session):
    # Solana SPL-token transfers report a base58 mint address (case-
    # sensitive, always well over a real ticker's length) as the asset when
    # no human-readable symbol is available. normalize_asset() must not
    # uppercase it -- that would silently corrupt an otherwise-valid mint
    # into an unresolvable string (this is what the CSV export and the
    # README's manual-lookup instructions rely on staying intact).
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    adapter = FakeAdapter("main", transactions=[_tx("t1", asset=mint)])
    sync_all(db_session, [adapter], FakePriceClient())

    saved = db_session.query(Transaction).one()
    assert saved.asset == mint


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
    assert adapter2.received_since == state.last_synced_at


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


def test_sync_normalizes_kraken_asset_codes_to_canonical_symbols(db_session):
    # Regression test for the on-chain-vs-Kraken asset collision: a Bitcoin
    # adapter transaction (asset="BTC") and a Kraken ledger transaction
    # (asset="XBT", Kraken's own code for Bitcoin) must both persist as the
    # same canonical "BTC" symbol, or compute_portfolio() would (incorrectly)
    # show them as two separate holdings for the same underlying asset.
    adapter = FakeAdapter(
        "main",
        transactions=[
            _tx("btc-onchain", asset="BTC"),
            _tx("btc-kraken", asset="XBT"),
        ],
    )
    reports = sync_all(db_session, [adapter], FakePriceClient(Decimal("100")))

    assert reports[0]["status"] == "ok"
    assert reports[0]["new_transactions"] == 2
    saved = db_session.query(Transaction).order_by(Transaction.external_id).all()
    assert {tx.asset for tx in saved} == {"BTC"}


def test_sync_normalizes_counter_asset_and_fee_asset(db_session):
    ntx = NormalizedTransaction(
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_type="exchange",
        source_name="kraken",
        account_label="main",
        tx_type="swap",
        asset="XBT",
        amount=Decimal("0.01"),
        counter_asset="ETH2",
        counter_amount=Decimal("0.2"),
        fee_amount=Decimal("0.001"),
        fee_asset="ETH2",
        external_id="swap-1",
        raw_json='{"asset": "XBT", "counter_asset": "ETH2", "fee_asset": "ETH2"}',
    )
    adapter = FakeAdapter("main", transactions=[ntx])
    sync_all(db_session, [adapter], FakePriceClient(Decimal("100")))

    saved = db_session.query(Transaction).one()
    assert saved.asset == "BTC"
    assert saved.counter_asset == "ETH"
    assert saved.fee_asset == "ETH"
    # The raw, un-normalized source values must still be recoverable from
    # raw_json for auditability.
    assert '"XBT"' in saved.raw_json
    assert '"ETH2"' in saved.raw_json


def test_sync_handles_missing_price_gracefully(db_session):
    class NonePriceClient:
        def get_price_chf(self, asset, on_date):
            return None

    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter], NonePriceClient())

    saved = db_session.query(Transaction).one()
    assert saved.price_chf is None
    assert saved.value_chf is None


@responses.activate
def test_sync_401_price_lookup_for_one_tx_does_not_abort_rest_of_batch(db_session):
    # Regression test: a CoinGecko 401 for one transaction's price lookup
    # (e.g. a too-old date on the free tier) must not raise out of
    # get_price_chf and abort the entire adapter's sync batch via sync_all's
    # per-adapter except/rollback. Only that one transaction should end up
    # with price_chf=None -- other transactions in the same
    # fetch_transactions() result must still persist successfully.
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        status=401,
    )
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/ethereum/history",
        json={"market_data": {"current_price": {"chf": "2500.0"}}},
        status=200,
    )

    adapter = FakeAdapter(
        "main",
        transactions=[
            _tx("t-no-historical-price", asset="BTC"),
            _tx("t-has-price", asset="ETH"),
        ],
    )
    reports = sync_all(db_session, [adapter], CoinGeckoPriceClient())

    assert reports == [
        {"source_name": "fake", "account_label": "main", "status": "ok", "new_transactions": 2}
    ]
    saved = {tx.external_id: tx for tx in db_session.query(Transaction).all()}
    assert saved["t-no-historical-price"].price_chf is None
    assert saved["t-no-historical-price"].value_chf is None
    assert saved["t-has-price"].price_chf == Decimal("2500.0")

    state = db_session.query(SyncState).one()
    assert state.last_error is None
