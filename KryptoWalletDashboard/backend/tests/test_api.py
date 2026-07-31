from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app, get_adapters, get_price_client, get_session
from app.models import Transaction


def _client(db_session, adapters=None, price_client=None):
    app.dependency_overrides[get_session] = lambda: db_session
    if adapters is not None:
        app.dependency_overrides[get_adapters] = lambda: adapters
    if price_client is not None:
        app.dependency_overrides[get_price_client] = lambda: price_client
    return TestClient(app)


def test_transactions_endpoint_returns_empty_list_initially(db_session):
    client = _client(db_session)
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_transactions_endpoint_returns_persisted_transactions(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/transactions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["external_id"] == "id1"
    app.dependency_overrides.clear()


def test_transactions_endpoint_filters_by_source_name(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="ethereum",
            account_label="main",
            tx_type="transfer_in",
            asset="ETH",
            amount=Decimal("1"),
            external_id="id2",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/transactions", params={"source_name": "ethereum"})
    body = response.json()
    assert len(body) == 1
    assert body[0]["external_id"] == "id2"
    app.dependency_overrides.clear()


def test_portfolio_endpoint_reflects_transactions(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            price_chf=Decimal("50000"),
            value_chf=Decimal("50000"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/portfolio")
    body = response.json()
    assert len(body) == 1
    assert body[0]["asset"] == "BTC"
    assert body[0]["amount"] == "1"
    app.dependency_overrides.clear()


def test_export_endpoint_returns_csv(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "id1" in response.text
    app.dependency_overrides.clear()


def test_sync_endpoint_runs_adapters_and_reports_results(db_session):
    class FakeAdapter:
        source_type = "chain"
        source_name = "fake"
        account_label = "main"

        def fetch_transactions(self, since):
            return []

    client = _client(db_session, adapters=[FakeAdapter()], price_client=object())
    response = client.post("/api/sync")
    assert response.status_code == 200
    assert response.json() == {
        "results": [{"source_name": "fake", "account_label": "main", "status": "ok", "new_transactions": 0}]
    }
    app.dependency_overrides.clear()
