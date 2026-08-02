from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction


def list_accounts(session: Session, adapters: list[TransactionAdapter] | None = None) -> list[dict]:
    """Every distinct (source_name, account_label) pair with any data in
    the DB -- from Transaction rows AND SyncState rows (a sync that always
    errors before writing any transaction still has a SyncState row, and
    should still show up here so it can be cleaned up).

    `is_configured` is purely informational (whether the pair is among the
    given `adapters`, e.g. built fresh from the current .env) -- it does
    NOT gate deletion; see delete_accounts.
    """
    configured = {(a.source_name, a.account_label) for a in adapters} if adapters is not None else set()

    tx_rows = session.execute(
        select(Transaction.source_name, Transaction.account_label, func.count(Transaction.id))
        .group_by(Transaction.source_name, Transaction.account_label)
    ).all()
    tx_counts = {(row[0], row[1]): row[2] for row in tx_rows}

    sync_by_account = {
        (s.source_name, s.account_label): s for s in session.execute(select(SyncState)).scalars().all()
    }

    all_pairs = set(tx_counts) | set(sync_by_account)

    result = []
    for source_name, account_label in sorted(all_pairs):
        sync_state = sync_by_account.get((source_name, account_label))
        result.append(
            {
                "source_name": source_name,
                "account_label": account_label,
                "transaction_count": tx_counts.get((source_name, account_label), 0),
                "last_synced_at": sync_state.last_synced_at if sync_state else None,
                "last_error": sync_state.last_error if sync_state else None,
                "is_configured": (source_name, account_label) in configured,
            }
        )
    return result


def delete_accounts(
    session: Session, pairs: list[tuple[str, str]], dry_run: bool = False
) -> list[dict]:
    """Delete Transaction/SyncState rows for exactly the given
    (source_name, account_label) pairs -- no notion of "still configured"
    here, unlike prune_stale_accounts below, which computes the pairs to
    pass in from what's no longer in .env. This is the primitive the
    Accounts page's explicit, user-chosen deletion uses directly.
    """
    reports = []
    for source_name, account_label in pairs:
        tx_count = session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.source_name == source_name,
                Transaction.account_label == account_label,
            )
        ).scalar_one()

        if not dry_run:
            session.execute(
                delete(Transaction).where(
                    Transaction.source_name == source_name,
                    Transaction.account_label == account_label,
                )
            )
            session.execute(
                delete(SyncState).where(
                    SyncState.source_name == source_name,
                    SyncState.account_label == account_label,
                )
            )

        reports.append(
            {
                "source_name": source_name,
                "account_label": account_label,
                "deleted_transactions": tx_count,
                "dry_run": dry_run,
            }
        )

    if not dry_run and pairs:
        session.commit()

    return reports


def prune_stale_accounts(
    session: Session, adapters: list[TransactionAdapter], dry_run: bool = False
) -> list[dict]:
    """Delete Transaction/SyncState rows for accounts that are no longer
    configured (i.e. not among `adapters`, which app.main builds fresh
    from the current .env on every request via build_adapters_from_config()).

    Matches on the (source_name, account_label) pair -- the same identity
    Transaction's unique constraint already uses -- not on the wallet
    address itself, so renaming a label is treated as removing the old
    account and adding a new one, while re-pointing a label at a different
    address keeps its existing history (address changes aren't detected;
    only removed labels are pruned).

    PriceCache rows are untouched: they're keyed by asset/date, not by
    account, and stay useful for any remaining account holding that asset.
    """
    configured = {(a.source_name, a.account_label) for a in adapters}

    existing = session.execute(
        select(Transaction.source_name, Transaction.account_label).distinct()
    ).all()
    stale = sorted({(row.source_name, row.account_label) for row in existing} - configured)

    return delete_accounts(session, stale, dry_run=dry_run)
