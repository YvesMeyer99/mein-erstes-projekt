from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class ExactDecimal(TypeDecorator):
    """Stores a Decimal as exact text.

    SQLAlchemy's plain Numeric type, when bound to a SQLite column, lets
    SQLite's NUMERIC type affinity silently coerce the value into an
    IEEE-754 float for storage, corrupting values like Decimal("0.1") on
    round-trip. Storing as TEXT instead means SQLite never reinterprets
    the value, so the Decimal round-trips exactly.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return Decimal(value) if value is not None else None


class UTCDateTime(TypeDecorator):
    """Stores a datetime as timezone-aware UTC, even on SQLite.

    SQLAlchemy's plain DateTime(timezone=True), when bound to a SQLite
    column, does not persist tzinfo: a timezone-aware datetime written in
    comes back naive after a round trip through the database (e.g. after
    `session.commit()` expires the object and it is re-queried). Every
    datetime this application writes to such a column is already
    constructed as timezone-aware UTC (adapters build timestamps via
    `datetime.fromtimestamp(..., tz=timezone.utc)`), so a naive value
    reaching `process_bind_param` indicates a bug upstream rather than a
    legitimate local time to coerce -- fail loudly instead of silently
    guessing the timezone. On the way out, `process_result_value`
    reattaches UTC tzinfo that SQLite dropped, restoring the original
    aware value.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "source_name", "account_label", "external_id",
            name="uq_transaction_source_account_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    source_type: Mapped[str] = mapped_column(String(20))
    source_name: Mapped[str] = mapped_column(String(50))
    account_label: Mapped[str] = mapped_column(String(100))
    tx_type: Mapped[str] = mapped_column(String(20))
    asset: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(ExactDecimal)
    counter_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counter_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal, nullable=True)
    price_chf: Mapped[Decimal | None] = mapped_column(ExactDecimal, nullable=True)
    value_chf: Mapped[Decimal | None] = mapped_column(ExactDecimal, nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal, nullable=True)
    fee_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fee_value_chf: Mapped[Decimal | None] = mapped_column(ExactDecimal, nullable=True)
    fee_included_in_amount: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_id: Mapped[str] = mapped_column(String(200))
    raw_json: Mapped[str] = mapped_column(String)


class PriceCache(Base):
    __tablename__ = "price_cache"
    __table_args__ = (
        UniqueConstraint("asset", "date", name="uq_price_cache_asset_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(20))
    date: Mapped[date] = mapped_column(Date)
    price_chf: Mapped[Decimal] = mapped_column(ExactDecimal)


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("source_name", "account_label", name="uq_sync_state_source_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(50))
    account_label: Mapped[str] = mapped_column(String(100))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
