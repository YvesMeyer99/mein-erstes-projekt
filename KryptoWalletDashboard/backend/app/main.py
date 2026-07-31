from datetime import datetime

from fastapi import Depends, FastAPI, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.factory import build_adapters_from_config
from app.csv_export import export_csv
from app.db import SessionLocal
from app.models import Transaction
from app.portfolio import compute_portfolio
from app.prices.coingecko import CoinGeckoPriceClient
from app.schemas import PortfolioEntryOut, TransactionOut
from app.sync import sync_all

app = FastAPI(title="Krypto-Wallet-Dashboard")


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


@app.get("/api/portfolio", response_model=list[PortfolioEntryOut])
def api_portfolio(session: Session = Depends(get_session)):
    return compute_portfolio(session)


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
        start, end, source_name, tx_type, account_label,
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
    csv_content = export_csv(session, start, end, source_name, tx_type, account_label)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transaktionen.csv"},
    )
