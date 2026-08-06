from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app, get_adapters, get_price_client, get_session
from app.models import Transaction


class StubPriceClient:
    def __init__(self, prices=None):
        self._prices = prices or {}

    def get_current_prices_chf(self, assets):
        return {asset: price for asset, price in self._prices.items() if asset in assets}


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

    client = _client(db_session, price_client=StubPriceClient())
    response = client.get("/api/portfolio")
    body = response.json()
    assert len(body) == 1
    assert body[0]["asset"] == "BTC"
    assert body[0]["amount"] == "1"
    app.dependency_overrides.clear()


def test_portfolio_endpoint_uses_live_price_when_available(db_session):
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

    client = _client(db_session, price_client=StubPriceClient({"BTC": Decimal("80000")}))
    response = client.get("/api/portfolio")
    body = response.json()
    assert body[0]["price_chf"] == "80000"
    assert body[0]["value_chf"] == "80000"
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


def test_config_get_endpoint_returns_all_fields_with_secrets_masked(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOLANA_ADDRESSES=main:abc\nKRAKEN_API_SECRET=real-secret\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.get("/api/config")

    assert response.status_code == 200
    fields = {f["name"]: f for f in response.json()["fields"]}
    assert fields["SOLANA_ADDRESSES"]["value"] == "main:abc"
    assert fields["KRAKEN_API_SECRET"]["value"] == ""
    assert fields["KRAKEN_API_SECRET"]["is_secret"] is True
    app.dependency_overrides.clear()


def test_config_post_endpoint_writes_file_and_reloads(db_session, tmp_path, monkeypatch):
    from app import config

    env_file = tmp_path / ".env"
    env_file.write_text("SOLANA_ADDRESSES=main:old\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))
    monkeypatch.delenv("SOLANA_ADDRESSES", raising=False)
    monkeypatch.setattr(config, "SOLANA_WALLETS", config.SOLANA_WALLETS)

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {"SOLANA_ADDRESSES": "main:new"}})

    assert response.status_code == 200
    assert "SOLANA_ADDRESSES=main:new" in env_file.read_text(encoding="utf-8")
    assert config.SOLANA_WALLETS[0].address == "new"
    app.dependency_overrides.clear()


def test_config_post_endpoint_leaves_secret_untouched_when_empty(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("KRAKEN_API_SECRET=existing\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {"KRAKEN_API_SECRET": ""}})

    assert response.status_code == 200
    assert "KRAKEN_API_SECRET=existing" in env_file.read_text(encoding="utf-8")
    app.dependency_overrides.clear()


def test_config_post_endpoint_rejects_value_with_injected_newline(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("KRAKEN_API_KEY=real-key\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post(
        "/api/config",
        json={"values": {"BITCOIN_ADDRESSES": "x\nKRAKEN_API_KEY=injected"}},
    )

    assert response.status_code == 400
    content = env_file.read_text(encoding="utf-8")
    assert content == "KRAKEN_API_KEY=real-key\n"
    assert "injected" not in content
    app.dependency_overrides.clear()


def test_config_post_endpoint_rejects_unknown_field_name(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOLANA_ADDRESSES=main:abc\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {"DATABASE_URL": "sqlite:///evil.db"}})

    assert response.status_code == 400
    content = env_file.read_text(encoding="utf-8")
    assert content == "SOLANA_ADDRESSES=main:abc\n"
    assert "DATABASE_URL" not in content
    app.dependency_overrides.clear()


def test_accounts_endpoint_lists_accounts_with_configured_flag(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="ledger",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    class FakeAdapter:
        source_type = "chain"
        source_name = "bitcoin"
        account_label = "ledger"

        def fetch_transactions(self, since):
            return []

    client = _client(db_session, adapters=[FakeAdapter()])
    response = client.get("/api/accounts")

    assert response.status_code == 200
    accounts = response.json()["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["source_name"] == "bitcoin"
    assert accounts[0]["transaction_count"] == 1
    assert accounts[0]["is_configured"] is True
    app.dependency_overrides.clear()


def test_accounts_delete_endpoint_deletes_the_given_accounts(db_session):
    db_session.add(
        Transaction(
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
            source_type="chain",
            source_name="bitcoin",
            account_label="ledger",
            tx_type="transfer_in",
            asset="BTC",
            amount=Decimal("1"),
            external_id="id1",
            raw_json="{}",
        )
    )
    db_session.commit()

    client = _client(db_session)
    response = client.post(
        "/api/accounts/delete",
        json={"accounts": [{"source_name": "bitcoin", "account_label": "ledger"}]},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {"source_name": "bitcoin", "account_label": "ledger", "deleted_transactions": 1, "dry_run": False}
    ]
    assert db_session.query(Transaction).count() == 0


def test_config_get_endpoint_includes_section_toggles(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CARDANO_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.get("/api/config")

    assert response.status_code == 200
    sections = {s["name"]: s["enabled"] for s in response.json()["sections"]}
    assert sections["Cardano"] is False
    assert sections["Bitcoin"] is True
    app.dependency_overrides.clear()


def test_config_post_endpoint_writes_section_toggles_and_reloads(db_session, tmp_path, monkeypatch):
    import os

    from app import config

    # api_post_config calls the real reload_config(), which calls
    # load_dotenv(..., override=True) -- that sets os.environ["BITCOIN_ENABLED"]
    # for the whole process, not just for this test. monkeypatch.setattr on the
    # config attribute alone (the plan's literal test code) does not undo that:
    # it only restores the Python attribute, not os.environ, so a later real
    # config._load_all_from_env() call elsewhere in the suite would re-derive
    # BITCOIN_ENABLED as False again. Same pitfall as
    # test_section_enabled_flag_is_false_when_env_var_is_false in
    # test_config.py -- snapshot and restore both by hand.
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    original_env_value = os.environ.get("BITCOIN_ENABLED")
    original_config_value = config.BITCOIN_ENABLED
    try:
        client = _client(db_session)
        response = client.post("/api/config", json={"values": {}, "sections": {"Bitcoin": False}})

        assert response.status_code == 200
        assert "BITCOIN_ENABLED=false" in env_file.read_text(encoding="utf-8")
        assert config.BITCOIN_ENABLED is False
    finally:
        if original_env_value is None:
            os.environ.pop("BITCOIN_ENABLED", None)
        else:
            os.environ["BITCOIN_ENABLED"] = original_env_value
        config.BITCOIN_ENABLED = original_config_value
    app.dependency_overrides.clear()


def test_config_post_endpoint_still_accepts_values_alongside_sections(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOLANA_ADDRESSES=old\n", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post(
        "/api/config",
        json={"values": {"SOLANA_ADDRESSES": "new"}, "sections": {}},
    )

    assert response.status_code == 200
    assert "SOLANA_ADDRESSES=new" in env_file.read_text(encoding="utf-8")
    app.dependency_overrides.clear()


def test_config_post_endpoint_rejects_unknown_section(db_session, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("app.env_file.ENV_FILE_PATH", str(env_file))

    client = _client(db_session)
    response = client.post("/api/config", json={"values": {}, "sections": {"NotASection": True}})

    assert response.status_code == 400
    app.dependency_overrides.clear()
    app.dependency_overrides.clear()
