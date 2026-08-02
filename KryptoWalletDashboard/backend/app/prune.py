from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction


def prune_stale_accounts(
    session: Session, adapters: list[TransactionAdapter], dry_run: bool = False
) -> list[dict]:
    """Delete Transaction/SyncState rows for accounts that are no longer
    configured (i.e. not among `adapters`, which app.main builds fresh from
    the current .env on every request via build_adapters_from_config()).

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
    stale = {(row.source_name, row.account_label) for row in existing} - configured

    reports = []
    for source_name, account_label in sorted(stale):
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

    if not dry_run:
        session.commit()

    return reports
