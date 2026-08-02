from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.prune import prune_stale_accounts


class FakeAdapter(TransactionAdapter):
    source_type = "chain"

    def __init__(self, source_name, account_label):
        super().__init__(account_label)
        self.source_name = source_name

    def fetch_transactions(self, since):
        return []


def _tx(source_name, account_label, external_id):
    return Transaction(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name=source_name,
        account_label=account_label,
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("1"),
        external_id=external_id,
        raw_json="{}",
    )


def _sync_state(source_name, account_label):
    return SyncState(
        source_name=source_name,
        account_label=account_label,
        last_synced_at=datetime.now(timezone.utc),
    )


def test_deletes_transactions_for_accounts_no_longer_configured(db_session):
    db_session.add(_tx("bitcoin", "old-ledger", "tx1"))
    db_session.commit()

    reports = prune_stale_accounts(db_session, adapters=[])

    assert db_session.query(Transaction).count() == 0
    assert reports == [
        {
            "source_name": "bitcoin",
            "account_label": "old-ledger",
            "deleted_transactions": 1,
            "dry_run": False,
        }
    ]


def test_keeps_transactions_for_accounts_still_configured(db_session):
    db_session.add(_tx("bitcoin", "ledger", "tx1"))
    db_session.add(_tx("solana", "gold-1", "tx2"))
    db_session.commit()

    reports = prune_stale_accounts(
        db_session,
        adapters=[FakeAdapter("bitcoin", "ledger"), FakeAdapter("solana", "gold-1")],
    )

    assert reports == []
    assert db_session.query(Transaction).count() == 2


def test_only_stale_accounts_are_removed_others_are_kept(db_session):
    db_session.add(_tx("bitcoin", "ledger", "tx1"))
    db_session.add(_tx("bitcoin", "old-exchange-deposit", "tx2"))
    db_session.commit()

    reports = prune_stale_accounts(db_session, adapters=[FakeAdapter("bitcoin", "ledger")])

    remaining = {tx.account_label for tx in db_session.query(Transaction).all()}
    assert remaining == {"ledger"}
    assert reports == [
        {
            "source_name": "bitcoin",
            "account_label": "old-exchange-deposit",
            "deleted_transactions": 1,
            "dry_run": False,
        }
    ]


def test_deletes_sync_state_for_unconfigured_accounts(db_session):
    db_session.add(_tx("bitcoin", "old-ledger", "tx1"))
    db_session.add(_sync_state("bitcoin", "old-ledger"))
    db_session.commit()

    prune_stale_accounts(db_session, adapters=[])

    assert db_session.query(SyncState).count() == 0


def test_keeps_sync_state_for_configured_accounts(db_session):
    db_session.add(_tx("bitcoin", "ledger", "tx1"))
    db_session.add(_sync_state("bitcoin", "ledger"))
    db_session.commit()

    prune_stale_accounts(db_session, adapters=[FakeAdapter("bitcoin", "ledger")])

    assert db_session.query(SyncState).count() == 1


def test_dry_run_reports_without_deleting(db_session):
    db_session.add(_tx("bitcoin", "old-ledger", "tx1"))
    db_session.add(_sync_state("bitcoin", "old-ledger"))
    db_session.commit()

    reports = prune_stale_accounts(db_session, adapters=[], dry_run=True)

    assert reports == [
        {
            "source_name": "bitcoin",
            "account_label": "old-ledger",
            "deleted_transactions": 1,
            "dry_run": True,
        }
    ]
    assert db_session.query(Transaction).count() == 1
    assert db_session.query(SyncState).count() == 1


def test_no_stale_accounts_returns_empty_list(db_session):
    db_session.add(_tx("bitcoin", "ledger", "tx1"))
    db_session.commit()

    reports = prune_stale_accounts(db_session, adapters=[FakeAdapter("bitcoin", "ledger")])

    assert reports == []


def test_empty_database_returns_empty_list(db_session):
    reports = prune_stale_accounts(db_session, adapters=[FakeAdapter("bitcoin", "ledger")])

    assert reports == []


def test_account_label_is_scoped_per_source_name(db_session):
    # An account_label like "main" used by two different sources must not
    # be confused for each other -- only the exact (source_name,
    # account_label) pair that's actually unconfigured gets pruned.
    db_session.add(_tx("ethereum", "main", "tx1"))
    db_session.add(_tx("vechain", "main", "tx2"))
    db_session.commit()

    reports = prune_stale_accounts(db_session, adapters=[FakeAdapter("vechain", "main")])

    remaining = {(tx.source_name, tx.account_label) for tx in db_session.query(Transaction).all()}
    assert remaining == {("vechain", "main")}
    assert reports == [
        {
            "source_name": "ethereum",
            "account_label": "main",
            "deleted_transactions": 1,
            "dry_run": False,
        }
    ]
