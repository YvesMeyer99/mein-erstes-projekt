from sqlalchemy import create_engine, inspect, text

from app.db import _migrate_existing_database


def _make_pre_fix_engine():
    """An in-memory SQLite DB shaped like a real user's file from before
    `fee_included_in_amount` existed: a `transactions` table with the old
    column set, populated with rows a real sync would have produced."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    source_type TEXT,
                    source_name TEXT,
                    account_label TEXT,
                    tx_type TEXT,
                    asset TEXT,
                    amount TEXT,
                    counter_asset TEXT,
                    counter_amount TEXT,
                    price_chf TEXT,
                    value_chf TEXT,
                    fee_amount TEXT,
                    fee_asset TEXT,
                    fee_value_chf TEXT,
                    external_id TEXT,
                    raw_json TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(source_name, tx_type, asset, amount, fee_amount, fee_asset, external_id) "
                "VALUES ('bitcoin', 'transfer_out', 'BTC', '0.0015', '0.0001', 'BTC', 'btc-1')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(source_name, tx_type, asset, amount, external_id) "
                "VALUES ('bitcoin', 'transfer_in', 'BTC', '0.01', 'btc-2')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(source_name, tx_type, asset, amount, fee_amount, fee_asset, external_id) "
                "VALUES ('ethereum', 'transfer_out', 'ETH', '1.0', '0.002', 'ETH', 'eth-1')"
            )
        )
    return engine


def test_adds_missing_column_to_pre_existing_table():
    engine = _make_pre_fix_engine()

    _migrate_existing_database(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("transactions")}
    assert "fee_included_in_amount" in columns


def test_backfills_true_for_fee_bearing_rows_from_amount_includes_fee_adapters():
    engine = _make_pre_fix_engine()

    _migrate_existing_database(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT fee_included_in_amount FROM transactions WHERE external_id = 'btc-1'")
        ).scalar_one()
    assert value == 1


def test_does_not_backfill_rows_without_a_fee():
    engine = _make_pre_fix_engine()

    _migrate_existing_database(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT fee_included_in_amount FROM transactions WHERE external_id = 'btc-2'")
        ).scalar_one()
    assert value == 0


def test_does_not_backfill_rows_from_adapters_where_amount_excludes_fee():
    engine = _make_pre_fix_engine()

    _migrate_existing_database(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT fee_included_in_amount FROM transactions WHERE external_id = 'eth-1'")
        ).scalar_one()
    assert value == 0


def test_is_idempotent_when_run_again_after_migration_already_applied():
    engine = _make_pre_fix_engine()

    _migrate_existing_database(engine)
    _migrate_existing_database(engine)

    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT fee_included_in_amount FROM transactions WHERE external_id = 'btc-1'")
        ).scalar_one()
    assert value == 1


def test_noop_when_transactions_table_does_not_exist_yet():
    engine = create_engine("sqlite:///:memory:")

    _migrate_existing_database(engine)  # must not raise
