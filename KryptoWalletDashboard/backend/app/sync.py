from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.prices.coingecko import get_or_fetch_price_chf


def _to_comparable_utc(dt: datetime) -> datetime:
    """Normalize to a naive UTC datetime for comparison.

    SQLite does not actually persist tzinfo: a timezone-aware datetime
    written to a `DateTime(timezone=True)` column comes back naive after
    a round trip through the database (e.g. after `session.commit()`
    expires the object). To compare such a value against a fresh,
    timezone-aware timestamp from an adapter without raising
    `TypeError: can't compare offset-naive and offset-aware datetimes`,
    both sides are normalized to naive UTC here.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _ensure_aware_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime read back from the DB is timezone-aware.

    Mirrors `_to_comparable_utc` but in the opposite direction: adapters
    (bitcoin.py, ethereum.py, kraken.py) compare `since` against their own
    timezone-aware timestamps and raise `TypeError` if `since` is naive.
    Since SQLite strips tzinfo on round trip, `since` must be normalized
    back to aware UTC before being handed to `adapter.fetch_transactions`.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _get_or_create_sync_state(session: Session, source_name: str, account_label: str) -> SyncState:
    state = session.execute(
        select(SyncState).where(
            SyncState.source_name == source_name, SyncState.account_label == account_label
        )
    ).scalar_one_or_none()
    if state is None:
        state = SyncState(source_name=source_name, account_label=account_label)
        session.add(state)
    return state


def _already_persisted(session: Session, source_name: str, account_label: str, external_id: str) -> bool:
    existing = session.execute(
        select(Transaction).where(
            Transaction.source_name == source_name,
            Transaction.account_label == account_label,
            Transaction.external_id == external_id,
        )
    ).scalar_one_or_none()
    return existing is not None


def sync_all(session: Session, adapters: list[TransactionAdapter], price_client) -> list[dict]:
    reports = []
    for adapter in adapters:
        state = _get_or_create_sync_state(session, adapter.source_name, adapter.account_label)
        since = _ensure_aware_utc(state.last_synced_at)
        try:
            normalized_txs = adapter.fetch_transactions(since)
            new_count = 0
            for ntx in normalized_txs:
                if _already_persisted(session, adapter.source_name, adapter.account_label, ntx.external_id):
                    continue

                price_chf = get_or_fetch_price_chf(session, price_client, ntx.asset, ntx.timestamp.date())
                value_chf = price_chf * ntx.amount if price_chf is not None else None

                fee_value_chf = None
                if ntx.fee_amount is not None and ntx.fee_asset is not None:
                    fee_price = get_or_fetch_price_chf(session, price_client, ntx.fee_asset, ntx.timestamp.date())
                    fee_value_chf = fee_price * ntx.fee_amount if fee_price is not None else None

                session.add(
                    Transaction(
                        timestamp=ntx.timestamp,
                        source_type=ntx.source_type,
                        source_name=ntx.source_name,
                        account_label=ntx.account_label,
                        tx_type=ntx.tx_type,
                        asset=ntx.asset,
                        amount=ntx.amount,
                        counter_asset=ntx.counter_asset,
                        counter_amount=ntx.counter_amount,
                        price_chf=price_chf,
                        value_chf=value_chf,
                        fee_amount=ntx.fee_amount,
                        fee_asset=ntx.fee_asset,
                        fee_value_chf=fee_value_chf,
                        external_id=ntx.external_id,
                        raw_json=ntx.raw_json,
                    )
                )
                new_count += 1

            if normalized_txs:
                latest_timestamp = max(ntx.timestamp for ntx in normalized_txs)
                if state.last_synced_at is None or _to_comparable_utc(
                    latest_timestamp
                ) > _to_comparable_utc(state.last_synced_at):
                    state.last_synced_at = latest_timestamp
            state.last_error = None
            session.commit()
            reports.append(
                {
                    "source_name": adapter.source_name,
                    "account_label": adapter.account_label,
                    "status": "ok",
                    "new_transactions": new_count,
                }
            )
        except Exception as exc:
            session.rollback()
            state = _get_or_create_sync_state(session, adapter.source_name, adapter.account_label)
            state.last_error = str(exc)
            session.commit()
            reports.append(
                {
                    "source_name": adapter.source_name,
                    "account_label": adapter.account_label,
                    "status": "error",
                    "error": str(exc),
                }
            )
    return reports
