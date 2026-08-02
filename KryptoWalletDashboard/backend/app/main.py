from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.factory import build_adapters_from_config
from app.config import reload_config
from app.csv_export import export_csv
from app.db import SessionLocal
from app.env_file import CONFIG_FIELDS, read_config_values, write_config_values
from app.models import Transaction
from app.portfolio import compute_portfolio
from app.prices.coingecko import CoinGeckoPriceClient
from app.prune import delete_accounts, list_accounts, prune_stale_accounts
from app.schemas import DeleteAccountsRequest, PortfolioEntryOut, TransactionOut
from app.sync import sync_all

app = FastAPI(title="Krypto-Wallet-Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_session():
    with SessionLocal() as session:
        yield session


def get_adapters():
    return build_adapters_from_config()


def get_price_client():
    return CoinGeckoPriceClient()


@app.post("/api/sync")
def api_sync(
    session: Session = Depends(get_session),
    adapters=Depends(get_adapters),
    price_client=Depends(get_price_client),
):
    return {"results": sync_all(session, adapters, price_client)}


@app.post("/api/prune")
def api_prune(
    dry_run: bool = False,
    session: Session = Depends(get_session),
    adapters=Depends(get_adapters),
):
    return {"results": prune_stale_accounts(session, adapters, dry_run=dry_run)}


@app.get("/api/config")
def api_get_config():
    values = read_config_values()
    return {
        "fields": [
            {
                "name": field.name,
                "section": field.section,
                "label": field.label,
                "is_secret": field.is_secret,
                "hint": field.hint,
                "value": values[field.name],
            }
            for field in CONFIG_FIELDS
        ]
    }


@app.post("/api/config")
def api_post_config(updates: dict[str, str]):
    write_config_values(updates)
    reload_config()
    return {"status": "ok"}


@app.get("/api/accounts")
def api_list_accounts(
    session: Session = Depends(get_session),
    adapters=Depends(get_adapters),
):
    return {"accounts": list_accounts(session, adapters)}


@app.post("/api/accounts/delete")
def api_delete_accounts(
    payload: DeleteAccountsRequest,
    session: Session = Depends(get_session),
):
    pairs = [(a.source_name, a.account_label) for a in payload.accounts]
    return {"results": delete_accounts(session, pairs)}


@app.get("/api/portfolio", response_model=list[PortfolioEntryOut])
def api_portfolio(
    session: Session = Depends(get_session),
    price_client=Depends(get_price_client),
):
    return compute_portfolio(session, price_client=price_client)


def _as_utc(dt: datetime | None) -> datetime | None:
    """Treat a naive datetime (e.g. parsed from a bare-date query param like
    ``?start=2024-01-01``) as UTC. The UTCDateTime column type rejects naive
    datetimes outright, so any user-supplied filter value must be made
    timezone-aware before it reaches a query.
    """
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _apply_filters(query, start, end, source_name, tx_type, account_label):
    if start is not None:
        query = query.where(Transaction.timestamp >= start)
    if end is not None:
        query = query.where(Transaction.timestamp <= end)
    if source_name is not None:
        query = query.where(Transaction.source_name == source_name)
    if tx_type is not None:
        query = query.where(Transaction.tx_type == tx_type)
    if account_label is not None:
        query = query.where(Transaction.account_label == account_label)
    return query


@app.get("/api/transactions", response_model=list[TransactionOut])
def api_transactions(
    start: datetime | None = None,
    end: datetime | None = None,
    source_name: str | None = None,
    tx_type: str | None = None,
    account_label: str | None = None,
    session: Session = Depends(get_session),
):
    query = _apply_filters(
        select(Transaction).order_by(Transaction.timestamp.desc()),
        _as_utc(start), _as_utc(end), source_name, tx_type, account_label,
    )
    return session.execute(query).scalars().all()


@app.get("/api/export")
def api_export(
    start: datetime | None = None,
    end: datetime | None = None,
    source_name: str | None = None,
    tx_type: str | None = None,
    account_label: str | None = None,
    session: Session = Depends(get_session),
):
    csv_content = export_csv(session, _as_utc(start), _as_utc(end), source_name, tx_type, account_label)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transaktionen.csv"},
    )
