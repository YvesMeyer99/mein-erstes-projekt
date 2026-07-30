from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction


def test_cannot_instantiate_abstract_adapter_directly():
    with pytest.raises(TypeError):
        TransactionAdapter("main")


def test_concrete_adapter_stores_account_label_and_can_fetch():
    class FakeAdapter(TransactionAdapter):
        source_type = "chain"
        source_name = "fake"

        def fetch_transactions(self, since):
            return []

    adapter = FakeAdapter("main")
    assert adapter.account_label == "main"
    assert adapter.fetch_transactions(None) == []


def test_normalized_transaction_requires_core_fields():
    with pytest.raises(Exception):
        NormalizedTransaction(timestamp=datetime.now(timezone.utc))


def test_normalized_transaction_accepts_valid_data():
    tx = NormalizedTransaction(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("0.5"),
        external_id="abc",
        raw_json="{}",
    )
    assert tx.amount == Decimal("0.5")
    assert tx.counter_asset is None
