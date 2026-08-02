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


def test_transactions_endpoint_accepts_naive_bare_date_start(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2023, 12, 31, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="before",
            raw_json="{}",
        )
    )
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="after",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/transactions", params={"start": "2024-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["external_id"] == "after"
    app.dependency_overrides.clear()


def test_export_endpoint_accepts_naive_bare_date_start(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2023, 12, 31, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="before",
            raw_json="{}",
        )
    )
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="after",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get("/api/export", params={"start": "2024-01-01"})
    assert response.status_code == 200
    assert "after" in response.text
    assert "before" not in response.text
    app.dependency_overrides.clear()


def test_transactions_endpoint_accepts_mixed_naive_start_and_aware_end(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2023, 12, 31, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="before",
            raw_json="{}",
        )
    )
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="in_range",
            raw_json="{}",
        )
    )
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="main",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="after",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.get(
        "/api/transactions",
        params={"start": "2024-01-01", "end": "2024-01-31T00:00:00+00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["external_id"] == "in_range"
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


def test_prune_endpoint_deletes_unconfigured_accounts(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="old-ledger",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session, adapters=[])
    response = client.post("/api/prune")
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"source_name": "bitcoin", "account_label": "old-ledger", "deleted_transactions": 1, "dry_run": False}
        ]
    }
    assert db_session.query(Transaction).count() == 0
    app.dependency_overrides.clear()


def test_prune_endpoint_supports_dry_run_query_param(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="old-ledger",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session, adapters=[])
    response = client.post("/api/prune", params={"dry_run": "true"})
    assert response.status_code == 200
    assert response.json()["results"][0]["dry_run"] is True
    assert db_session.query(Transaction).count() == 1
    app.dependency_overrides.clear()
