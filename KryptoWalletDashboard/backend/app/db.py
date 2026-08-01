from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)

# source_name values whose on-chain adapters compute `amount` as the total
# wallet-balance decrease for an outgoing transfer (fee already baked in),
# rather than as an independent figure from `fee_amount`. See
# app.portfolio.compute_portfolio and app.schemas.NormalizedTransaction.
_FEE_INCLUDED_IN_AMOUNT_SOURCES = ("bitcoin", "cardano", "solana")


def _migrate_existing_database(engine) -> None:
    """Add columns introduced after a database file was first created, and
    backfill any data those columns need to be correct on rows written
    before the column existed.

    Base.metadata.create_all() only creates missing TABLES, not missing
    COLUMNS on tables that already exist. This project has no formal
    migration tooling (a single-user SQLite file) -- without this, adding
    a column to an existing model would silently do nothing against an
    existing database file, and the ORM would then be reading/writing a
    column the actual table doesn't have.
    """
    inspector = inspect(engine)
    if not inspector.has_table("transactions"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("transactions")}
    if "fee_included_in_amount" in existing_columns:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE transactions "
                "ADD COLUMN fee_included_in_amount BOOLEAN NOT NULL DEFAULT 0"
            )
        )
        # Every row the Bitcoin/Cardano/Solana adapters wrote before this
        # column existed already had the fee baked into `amount` -- that
        # computation never changed, only app.portfolio's awareness of it
        # did -- so any such row that carries a fee needs the flag set
        # retroactively, or compute_portfolio() would still double-subtract
        # its fee even after this migration runs.
        placeholders = ", ".join(f"'{name}'" for name in _FEE_INCLUDED_IN_AMOUNT_SOURCES)
        conn.execute(
            text(
                "UPDATE transactions SET fee_included_in_amount = 1 "
                f"WHERE source_name IN ({placeholders}) AND fee_amount IS NOT NULL"
            )
        )


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_existing_database(engine)
