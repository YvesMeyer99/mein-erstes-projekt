# Krypto-Wallet-Dashboard – Backend Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-run Python backend that syncs transactions from Bitcoin, Ethereum and Kraken, enriches them with historical CHF prices, stores them in SQLite, and exposes a REST API for portfolio overview, a filterable transaction list, and CSV export.

**Architecture:** Adapter pattern (one class per data source, common `fetch_transactions` interface) feeding a sync orchestrator that normalizes, deduplicates, price-enriches (CoinGecko) and persists transactions (SQLAlchemy + SQLite). FastAPI exposes `/api/sync`, `/api/portfolio`, `/api/transactions`, `/api/export` on top of that data.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, Pydantic v2, `requests` for HTTP calls, `responses` for mocking HTTP in tests, pytest.

**Related spec:** [`docs/superpowers/specs/2026-07-30-krypto-wallet-dashboard-design.md`](../specs/2026-07-30-krypto-wallet-dashboard-design.md)

**Scope notes (decided during planning, not silent deviations from the spec):**
- This plan covers **Phase 1 only**: Bitcoin, Ethereum, Kraken. Remaining EVM chains, Binance/Coinbase/MEXC (Phase 2) and Solana/Cardano/VeChain (Phase 3) are separate follow-up plans, as agreed in the design.
- **ESTV year-end prices** (`year_end_prices` table, Vermögenssteuerwert) are explicitly deferred to a follow-up plan — confirmed with the user. This plan only implements CoinGecko per-transaction pricing.
- **Ethereum adapter covers native ETH transfers only**, not ERC-20 token transfers. Token tracking is deferred to Phase 2 alongside the other EVM chains, to keep this adapter's scope testable in isolation.
- On-chain wallet adapters (Bitcoin, Ethereum) can only observe fund movement, not economic intent — they produce `transfer_in`/`transfer_out` (+ `fee` on outgoing txs), never `buy`/`sell`/`swap`. Those tx types come from exchange adapters (Kraken here), where a "buy" or "sell" against fiat is modeled as a `swap` (fiat is just another asset) — this is the same normalized representation the spec's `counter_asset`/`counter_amount` fields were designed for.
- The **React frontend is a separate follow-up plan**; this plan produces a fully testable backend (pytest + manual `curl`/`TestClient` checks), no UI.

---

## File Structure

```
KryptoWalletDashboard/
  backend/
    requirements.txt
    pytest.ini
    .env.example
    README.md
    app/
      __init__.py
      config.py                 # env var loading: wallet addresses, API keys, DB URL
      schemas.py                 # NormalizedTransaction, TransactionOut (Pydantic)
      models.py                  # SQLAlchemy models: Transaction, PriceCache, SyncState
      db.py                      # engine/session setup
      init_db.py                 # one-off script: create tables
      adapters/
        __init__.py
        base.py                  # TransactionAdapter ABC
        bitcoin.py                # BitcoinAdapter
        ethereum.py               # EthereumAdapter
        kraken.py                 # KrakenAdapter
        factory.py                 # build_adapters_from_config()
      prices/
        __init__.py
        coingecko.py               # CoinGeckoPriceClient + get_or_fetch_price_chf()
      sync.py                     # sync_all() orchestration
      portfolio.py                 # compute_portfolio()
      csv_export.py                # export_csv()
      main.py                      # FastAPI app + routes
    tests/
      __init__.py
      conftest.py                  # db_session fixture (in-memory SQLite)
      test_config.py
      test_models.py
      test_adapter_base.py
      test_bitcoin_adapter.py
      test_ethereum_adapter.py
      test_kraken_adapter.py
      test_coingecko_prices.py
      test_sync.py
      test_portfolio.py
      test_csv_export.py
      test_api.py
```

---

### Task 1: Project Setup & Config

**Files:**
- Create: `KryptoWalletDashboard/backend/requirements.txt`
- Create: `KryptoWalletDashboard/backend/pytest.ini`
- Create: `KryptoWalletDashboard/backend/.env.example`
- Create: `KryptoWalletDashboard/backend/app/__init__.py`
- Create: `KryptoWalletDashboard/backend/app/config.py`
- Create: `KryptoWalletDashboard/backend/tests/__init__.py`
- Test: `KryptoWalletDashboard/backend/tests/test_config.py`

- [ ] **Step 1: Create the project skeleton and dependency list**

`KryptoWalletDashboard/backend/requirements.txt`:
```
fastapi
uvicorn[standard]
sqlalchemy
pydantic
requests
python-dotenv
pytest
responses
httpx
```

`KryptoWalletDashboard/backend/pytest.ini`:
```ini
[pytest]
pythonpath = .
```

`KryptoWalletDashboard/backend/app/__init__.py`: empty file.

`KryptoWalletDashboard/backend/tests/__init__.py`: empty file.

- [ ] **Step 2: Create a virtual environment and install dependencies**

Run (from `KryptoWalletDashboard/backend/`):
```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```
Expected: all packages install without error.

- [ ] **Step 3: Create the `.env.example` documenting required config**

`KryptoWalletDashboard/backend/.env.example`:
```
# Bitcoin: comma-separated label:address pairs
BITCOIN_ADDRESSES=main:bc1qexampleaddress

# Ethereum: comma-separated label:address pairs
ETHEREUM_ADDRESSES=main:0xExampleAddress
ETHERSCAN_API_KEY=your-etherscan-api-key

# Kraken: read-only API key (no trade/withdraw permission!)
KRAKEN_API_KEY=your-read-only-kraken-key
KRAKEN_API_SECRET=your-read-only-kraken-secret

# Optional, defaults to a local SQLite file
DATABASE_URL=sqlite:///./krypto_dashboard.db
```

- [ ] **Step 4: Write the failing test for wallet-list parsing**

`KryptoWalletDashboard/backend/tests/test_config.py`:
```python
from app.config import parse_wallets


def test_parse_wallets_returns_empty_list_for_none():
    assert parse_wallets(None) == []


def test_parse_wallets_returns_empty_list_for_empty_string():
    assert parse_wallets("") == []


def test_parse_wallets_parses_single_entry():
    result = parse_wallets("main:bc1qexample")
    assert len(result) == 1
    assert result[0].label == "main"
    assert result[0].address == "bc1qexample"


def test_parse_wallets_parses_multiple_entries_and_trims_whitespace():
    result = parse_wallets(" main : bc1qexample , savings:bc1qother ")
    assert result == [
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="main", address="bc1qexample"),
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="savings", address="bc1qother"),
    ]
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'` (or `ImportError: cannot import name 'parse_wallets'`).

- [ ] **Step 6: Implement `app/config.py`**

```python
from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class WalletConfig:
    label: str
    address: str


def parse_wallets(env_value: str | None) -> list[WalletConfig]:
    if not env_value:
        return []
    wallets = []
    for entry in env_value.split(","):
        label, _, address = entry.partition(":")
        label = label.strip()
        address = address.strip()
        if address:
            wallets.append(WalletConfig(label=label, address=address))
    return wallets


BITCOIN_WALLETS = parse_wallets(os.getenv("BITCOIN_ADDRESSES"))
ETHEREUM_WALLETS = parse_wallets(os.getenv("ETHEREUM_ADDRESSES"))
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./krypto_dashboard.db")
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add KryptoWalletDashboard/backend/requirements.txt KryptoWalletDashboard/backend/pytest.ini KryptoWalletDashboard/backend/.env.example KryptoWalletDashboard/backend/app/__init__.py KryptoWalletDashboard/backend/app/config.py KryptoWalletDashboard/backend/tests/__init__.py KryptoWalletDashboard/backend/tests/test_config.py
git commit -m "feat: project setup and wallet config parsing"
```

---

### Task 2: Database Models & Test Fixture

**Files:**
- Create: `KryptoWalletDashboard/backend/app/models.py`
- Create: `KryptoWalletDashboard/backend/app/db.py`
- Create: `KryptoWalletDashboard/backend/app/init_db.py`
- Create: `KryptoWalletDashboard/backend/tests/conftest.py`
- Test: `KryptoWalletDashboard/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test for the `Transaction` model's uniqueness constraint**

`KryptoWalletDashboard/backend/tests/conftest.py`:
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
```

`KryptoWalletDashboard/backend/tests/test_models.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Transaction


def _make_transaction(**overrides):
    kwargs = dict(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("0.1"),
        external_id="tx123",
        raw_json="{}",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_transaction_can_be_inserted(db_session):
    db_session.add(_make_transaction())
    db_session.commit()
    assert db_session.query(Transaction).count() == 1


def test_duplicate_external_id_for_same_source_and_account_is_rejected(db_session):
    db_session.add(_make_transaction())
    db_session.commit()
    db_session.add(_make_transaction())
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_external_id_allowed_for_different_account(db_session):
    db_session.add(_make_transaction(account_label="main"))
    db_session.commit()
    db_session.add(_make_transaction(account_label="savings"))
    db_session.commit()
    assert db_session.query(Transaction).count() == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`.

- [ ] **Step 3: Implement `app/models.py`**

```python
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str] = mapped_column(String(20))
    source_name: Mapped[str] = mapped_column(String(50))
    account_label: Mapped[str] = mapped_column(String(100))
    tx_type: Mapped[str] = mapped_column(String(20))
    asset: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(36, 18))
    counter_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    counter_amount: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    price_chf: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    value_chf: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    fee_asset: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fee_value_chf: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
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
    price_chf: Mapped[Decimal] = mapped_column(Numeric(36, 18))


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("source_name", "account_label", name="uq_sync_state_source_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(50))
    account_label: Mapped[str] = mapped_column(String(100))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Add `app/db.py` and `app/init_db.py` (no test — thin wiring, exercised via Task 11's API tests and manual smoke test in Task 12)**

`KryptoWalletDashboard/backend/app/db.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL
from app.models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)
```

`KryptoWalletDashboard/backend/app/init_db.py`:
```python
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("Datenbank initialisiert.")
```

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/backend/app/models.py KryptoWalletDashboard/backend/app/db.py KryptoWalletDashboard/backend/app/init_db.py KryptoWalletDashboard/backend/tests/conftest.py KryptoWalletDashboard/backend/tests/test_models.py
git commit -m "feat: SQLAlchemy models and DB session setup"
```

---

### Task 3: Normalized Transaction Schema & Adapter Base Class

**Files:**
- Create: `KryptoWalletDashboard/backend/app/schemas.py`
- Create: `KryptoWalletDashboard/backend/app/adapters/__init__.py`
- Create: `KryptoWalletDashboard/backend/app/adapters/base.py`
- Test: `KryptoWalletDashboard/backend/tests/test_adapter_base.py`

- [ ] **Step 1: Write the failing test**

`KryptoWalletDashboard/backend/tests/test_adapter_base.py`:
```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_adapter_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters'`.

- [ ] **Step 3: Implement `app/schemas.py`**

```python
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class NormalizedTransaction(BaseModel):
    timestamp: datetime
    source_type: str
    source_name: str
    account_label: str
    tx_type: str
    asset: str
    amount: Decimal
    counter_asset: str | None = None
    counter_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    fee_asset: str | None = None
    external_id: str
    raw_json: str


class TransactionOut(BaseModel):
    id: int
    timestamp: datetime
    source_type: str
    source_name: str
    account_label: str
    tx_type: str
    asset: str
    amount: Decimal
    counter_asset: str | None
    counter_amount: Decimal | None
    price_chf: Decimal | None
    value_chf: Decimal | None
    fee_amount: Decimal | None
    fee_asset: str | None
    external_id: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Implement `app/adapters/__init__.py` and `app/adapters/base.py`**

`KryptoWalletDashboard/backend/app/adapters/__init__.py`: empty file.

`KryptoWalletDashboard/backend/app/adapters/base.py`:
```python
from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas import NormalizedTransaction


class TransactionAdapter(ABC):
    source_type: str
    source_name: str

    def __init__(self, account_label: str):
        self.account_label = account_label

    @abstractmethod
    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        """Return transactions newer than `since` (or all, if `since` is None)."""
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_adapter_base.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add KryptoWalletDashboard/backend/app/schemas.py KryptoWalletDashboard/backend/app/adapters/__init__.py KryptoWalletDashboard/backend/app/adapters/base.py KryptoWalletDashboard/backend/tests/test_adapter_base.py
git commit -m "feat: normalized transaction schema and adapter base class"
```

---

### Task 4: Bitcoin Adapter

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/bitcoin.py`
- Test: `KryptoWalletDashboard/backend/tests/test_bitcoin_adapter.py`

**Data source:** `https://blockstream.info/api/address/{address}/txs` (Blockstream Esplora API, no key required). Each tx has `txid`, `status.block_time` (unix seconds, absent if unconfirmed), `vin[].prevout.{scriptpubkey_address,value}`, `vout[].{scriptpubkey_address,value}` (values in satoshis).

- [ ] **Step 1: Write the failing test with a mocked API response**

`KryptoWalletDashboard/backend/tests/test_bitcoin_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.bitcoin import BitcoinAdapter

ADDRESS = "bc1qexampleaddress"


def _tx(txid, block_time, vin, vout):
    return {
        "txid": txid,
        "status": {"confirmed": True, "block_time": block_time},
        "vin": vin,
        "vout": vout,
    }


@responses.activate
def test_incoming_transaction_is_transfer_in():
    incoming = _tx(
        "tx-in",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[incoming],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "BTC"
    assert tx.amount == Decimal("100000") / Decimal(10**8)
    assert tx.fee_amount is None
    assert tx.external_id == "tx-in"
    assert tx.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)


@responses.activate
def test_outgoing_transaction_is_transfer_out_with_fee():
    outgoing = _tx(
        "tx-out",
        1700000100,
        vin=[{"prevout": {"scriptpubkey_address": ADDRESS, "value": 200000}}],
        vout=[
            {"scriptpubkey_address": "someone-else", "value": 150000},
            {"scriptpubkey_address": ADDRESS, "value": 40000},
        ],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[outgoing],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_out"
    # net change for our address: -200000 (spent) + 40000 (change back) = -160000 sats
    assert tx.amount == Decimal("160000") / Decimal(10**8)
    assert tx.fee_amount == Decimal("10000") / Decimal(10**8)
    assert tx.fee_asset == "BTC"


@responses.activate
def test_unconfirmed_transaction_is_skipped():
    unconfirmed = {
        "txid": "tx-pending",
        "status": {"confirmed": False},
        "vin": [{"prevout": {"scriptpubkey_address": "someone-else", "value": 1000}}],
        "vout": [{"scriptpubkey_address": ADDRESS, "value": 500}],
    }
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[unconfirmed],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_transactions():
    older = _tx(
        "tx-old",
        1700000000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    newer = _tx(
        "tx-new",
        1700001000,
        vin=[{"prevout": {"scriptpubkey_address": "someone-else", "value": 200000}}],
        vout=[{"scriptpubkey_address": ADDRESS, "value": 100000}],
    )
    responses.add(
        responses.GET,
        f"https://blockstream.info/api/address/{ADDRESS}/txs",
        json=[older, newer],
        status=200,
    )

    adapter = BitcoinAdapter(account_label="main", address=ADDRESS)
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["tx-new"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_bitcoin_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.bitcoin'`.

- [ ] **Step 3: Implement `app/adapters/bitcoin.py`**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

SATS_PER_BTC = Decimal(10**8)


class BitcoinAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"
    API_BASE = "https://blockstream.info/api"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        response = requests.get(f"{self.API_BASE}/address/{self.address}/txs", timeout=10)
        response.raise_for_status()
        results: list[NormalizedTransaction] = []
        for tx in response.json():
            block_time = tx.get("status", {}).get("block_time")
            if block_time is None:
                continue
            timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue

            vin_value = sum(
                vin["prevout"]["value"]
                for vin in tx["vin"]
                if vin.get("prevout", {}).get("scriptpubkey_address") == self.address
            )
            vout_value = sum(
                vout["value"]
                for vout in tx["vout"]
                if vout.get("scriptpubkey_address") == self.address
            )
            net_sats = vout_value - vin_value
            if net_sats == 0:
                continue

            fee_amount = None
            fee_asset = None
            if net_sats < 0:
                total_vin = sum(vin["prevout"]["value"] for vin in tx["vin"])
                total_vout = sum(vout["value"] for vout in tx["vout"])
                fee_sats = total_vin - total_vout
                fee_amount = Decimal(fee_sats) / SATS_PER_BTC
                fee_asset = "BTC"

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in" if net_sats > 0 else "transfer_out",
                    asset="BTC",
                    amount=Decimal(abs(net_sats)) / SATS_PER_BTC,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["txid"],
                    raw_json=json.dumps(tx),
                )
            )
        return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_bitcoin_adapter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/bitcoin.py KryptoWalletDashboard/backend/tests/test_bitcoin_adapter.py
git commit -m "feat: Bitcoin adapter via Blockstream API"
```

---

### Task 5: Ethereum Adapter

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/ethereum.py`
- Test: `KryptoWalletDashboard/backend/tests/test_ethereum_adapter.py`

**Data source:** `https://api.etherscan.io/api?module=account&action=txlist&address={address}&apikey={key}` — native ETH transfers only (no ERC-20, see plan-level scope note).

- [ ] **Step 1: Write the failing test with a mocked API response**

`KryptoWalletDashboard/backend/tests/test_ethereum_adapter.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

import responses

from app.adapters.ethereum import EthereumAdapter

ADDRESS = "0xExampleAddress"


def _tx(tx_hash, timestamp, from_addr, to_addr, value_wei, is_error="0", gas_used="21000", gas_price="20000000000"):
    return {
        "hash": tx_hash,
        "timeStamp": str(timestamp),
        "from": from_addr,
        "to": to_addr,
        "value": str(value_wei),
        "gasUsed": gas_used,
        "gasPrice": gas_price,
        "isError": is_error,
    }


@responses.activate
def test_incoming_transaction_is_transfer_in():
    tx = _tx("0xin", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_in"
    assert result.asset == "ETH"
    assert result.amount == Decimal("1")
    assert result.fee_amount is None


@responses.activate
def test_outgoing_transaction_is_transfer_out_with_gas_fee():
    tx = _tx("0xout", 1700000100, ADDRESS, "0xSomeoneElse", 2 * 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    result = results[0]
    assert result.tx_type == "transfer_out"
    assert result.amount == Decimal("2")
    assert result.fee_amount == (Decimal("21000") * Decimal("20000000000")) / Decimal(10**18)
    assert result.fee_asset == "ETH"


@responses.activate
def test_failed_transaction_is_skipped():
    tx = _tx("0xfailed", 1700000200, ADDRESS, "0xSomeoneElse", 10**18, is_error="1")
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [tx]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    assert adapter.fetch_transactions(None) == []


@responses.activate
def test_since_filters_out_older_transactions():
    older = _tx("0xold", 1700000000, "0xSomeoneElse", ADDRESS, 10**18)
    newer = _tx("0xnew", 1700001000, "0xSomeoneElse", ADDRESS, 10**18)
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "1", "message": "OK", "result": [older, newer]},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [r.external_id for r in results] == ["0xnew"]


@responses.activate
def test_no_transactions_found_does_not_raise():
    responses.add(
        responses.GET,
        "https://api.etherscan.io/api",
        json={"status": "0", "message": "No transactions found", "result": []},
        status=200,
    )

    adapter = EthereumAdapter(account_label="main", address=ADDRESS, api_key="key")
    assert adapter.fetch_transactions(None) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_ethereum_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.ethereum'`.

- [ ] **Step 3: Implement `app/adapters/ethereum.py`**

```python
import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

WEI_PER_ETH = Decimal(10**18)


class EthereumAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "ethereum"
    API_URL = "https://api.etherscan.io/api"

    def __init__(self, account_label: str, address: str, api_key: str):
        super().__init__(account_label)
        self.address = address
        self.api_key = api_key

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        params = {
            "module": "account",
            "action": "txlist",
            "address": self.address,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "asc",
            "apikey": self.api_key,
        }
        response = requests.get(self.API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "1" and data.get("message") != "No transactions found":
            raise RuntimeError(f"Etherscan-Fehler: {data.get('message')}")

        address_lower = self.address.lower()
        results: list[NormalizedTransaction] = []
        for tx in data.get("result", []):
            if tx.get("isError") == "1":
                continue
            timestamp = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            value_eth = Decimal(tx["value"]) / WEI_PER_ETH
            if value_eth == 0:
                continue

            is_outgoing = tx["from"].lower() == address_lower
            fee_amount = None
            fee_asset = None
            if is_outgoing:
                fee_amount = (Decimal(tx["gasUsed"]) * Decimal(tx["gasPrice"])) / WEI_PER_ETH
                fee_asset = "ETH"

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out" if is_outgoing else "transfer_in",
                    asset="ETH",
                    amount=value_eth,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["hash"],
                    raw_json=json.dumps(tx),
                )
            )
        return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_ethereum_adapter.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/ethereum.py KryptoWalletDashboard/backend/tests/test_ethereum_adapter.py
git commit -m "feat: Ethereum adapter via Etherscan API"
```

---

### Task 6: Kraken Adapter

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/kraken.py`
- Test: `KryptoWalletDashboard/backend/tests/test_kraken_adapter.py`

**Data source:** Kraken private `Ledgers` endpoint (`POST /0/private/Ledgers`, HMAC-SHA512 signed). Ledger entries of type `deposit`/`withdrawal`/`staking` map directly. Type `trade` always comes in **pairs** sharing the same `refid` (one leg per asset) — these are paired into a single `swap` transaction with `counter_asset`/`counter_amount`, since a "buy" or "sell" against fiat is just a swap where one side is a fiat currency.

- [ ] **Step 1: Write the failing test with a mocked API response**

`KryptoWalletDashboard/backend/tests/test_kraken_adapter.py`:
```python
from decimal import Decimal

import responses

from app.adapters.kraken import KrakenAdapter


def _ledger_response(ledger: dict) -> dict:
    return {"error": [], "result": {"ledger": ledger, "count": len(ledger)}}


@responses.activate
def test_deposit_is_transfer_in():
    ledger = {
        "L1": {
            "refid": "R1",
            "time": 1700000000.0,
            "type": "deposit",
            "asset": "XBT",
            "amount": "0.5000000000",
            "fee": "0.0000000000",
        }
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "transfer_in"
    assert tx.asset == "XBT"
    assert tx.amount == Decimal("0.5")
    assert tx.external_id == "L1"


@responses.activate
def test_staking_reward_is_mapped():
    ledger = {
        "L2": {
            "refid": "R2",
            "time": 1700000100.0,
            "type": "staking",
            "asset": "ETH2",
            "amount": "0.0100000000",
            "fee": "0.0000000000",
        }
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    assert results[0].tx_type == "staking_reward"
    assert results[0].amount == Decimal("0.01")


@responses.activate
def test_trade_pair_is_merged_into_a_swap():
    ledger = {
        "T1": {
            "refid": "TRADE1",
            "time": 1700000200.0,
            "type": "trade",
            "asset": "ZEUR",
            "amount": "-100.0000000000",
            "fee": "0.2600000000",
        },
        "T2": {
            "refid": "TRADE1",
            "time": 1700000200.0,
            "type": "trade",
            "asset": "XBT",
            "amount": "0.0030000000",
            "fee": "0.0000000000",
        },
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    results = adapter.fetch_transactions(None)

    assert len(results) == 1
    tx = results[0]
    assert tx.tx_type == "swap"
    assert tx.asset == "XBT"
    assert tx.amount == Decimal("0.003")
    assert tx.counter_asset == "ZEUR"
    assert tx.counter_amount == Decimal("100")
    assert tx.fee_amount == Decimal("0.26")
    assert tx.fee_asset == "ZEUR"
    assert tx.external_id == "TRADE1"


@responses.activate
def test_since_filters_out_older_entries():
    ledger = {
        "L1": {"refid": "R1", "time": 1700000000.0, "type": "deposit", "asset": "XBT", "amount": "0.1", "fee": "0"},
        "L2": {"refid": "R2", "time": 1700001000.0, "type": "deposit", "asset": "XBT", "amount": "0.2", "fee": "0"},
    }
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json=_ledger_response(ledger),
        status=200,
    )

    from datetime import datetime, timezone

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    since = datetime.fromtimestamp(1700000500, tz=timezone.utc)
    results = adapter.fetch_transactions(since)

    assert [tx.external_id for tx in results] == ["L2"]


@responses.activate
def test_api_error_raises():
    responses.add(
        responses.POST,
        "https://api.kraken.com/0/private/Ledgers",
        json={"error": ["EAPI:Invalid key"], "result": {}},
        status=200,
    )

    adapter = KrakenAdapter(account_label="kraken-main", api_key="key", api_secret="c2VjcmV0")
    try:
        adapter.fetch_transactions(None)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "EAPI:Invalid key" in str(exc)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_kraken_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.kraken'`.

- [ ] **Step 3: Implement `app/adapters/kraken.py`**

```python
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

NON_TRADE_TYPE_MAP = {
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "staking": "staking_reward",
}


class KrakenAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "kraken"
    API_URL = "https://api.kraken.com"
    LEDGERS_PATH = "/0/private/Ledgers"

    def __init__(self, account_label: str, api_key: str, api_secret: str):
        super().__init__(account_label)
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, urlpath: str, data: dict) -> str:
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        return base64.b64encode(signature.digest()).decode()

    def _fetch_ledger(self, since: datetime | None) -> dict:
        data = {"nonce": str(int(time.time() * 1000))}
        if since is not None:
            data["start"] = str(int(since.timestamp()))
        headers = {"API-Key": self.api_key, "API-Sign": self._sign(self.LEDGERS_PATH, data)}
        response = requests.post(self.API_URL + self.LEDGERS_PATH, data=data, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Kraken-Fehler: {', '.join(payload['error'])}")
        return payload["result"].get("ledger", {})

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        ledger = self._fetch_ledger(since)

        trade_legs_by_refid: dict[str, list[tuple[str, dict]]] = {}
        other_entries: list[tuple[str, dict]] = []
        for entry_id, entry in ledger.items():
            if entry["type"] == "trade":
                trade_legs_by_refid.setdefault(entry["refid"], []).append((entry_id, entry))
            else:
                other_entries.append((entry_id, entry))

        results: list[NormalizedTransaction] = []
        results.extend(self._build_non_trade_transactions(other_entries, since))
        results.extend(self._build_swap_transactions(trade_legs_by_refid, since))
        return results

    def _build_non_trade_transactions(self, entries, since):
        results = []
        for entry_id, entry in entries:
            tx_type = NON_TRADE_TYPE_MAP.get(entry["type"])
            if tx_type is None:
                continue
            timestamp = datetime.fromtimestamp(float(entry["time"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            fee = Decimal(entry.get("fee", "0"))
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type=tx_type,
                    asset=entry["asset"],
                    amount=abs(Decimal(entry["amount"])),
                    fee_amount=fee if fee != 0 else None,
                    fee_asset=entry["asset"] if fee != 0 else None,
                    external_id=entry_id,
                    raw_json=json.dumps(entry),
                )
            )
        return results

    def _build_swap_transactions(self, trade_legs_by_refid, since):
        results = []
        for refid, legs in trade_legs_by_refid.items():
            if len(legs) != 2:
                continue
            (_, entry_a), (_, entry_b) = legs
            sold, bought = (
                (entry_a, entry_b) if Decimal(entry_a["amount"]) < 0 else (entry_b, entry_a)
            )
            timestamp = datetime.fromtimestamp(float(bought["time"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            bought_fee = Decimal(bought.get("fee", "0"))
            sold_fee = Decimal(sold.get("fee", "0"))
            fee_amount = bought_fee + sold_fee
            fee_asset = None
            if bought_fee != 0:
                fee_asset = bought["asset"]
            elif sold_fee != 0:
                fee_asset = sold["asset"]
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="swap",
                    asset=bought["asset"],
                    amount=Decimal(bought["amount"]),
                    counter_asset=sold["asset"],
                    counter_amount=abs(Decimal(sold["amount"])),
                    fee_amount=fee_amount if fee_amount != 0 else None,
                    fee_asset=fee_asset,
                    external_id=refid,
                    raw_json=json.dumps({"sold": sold, "bought": bought}),
                )
            )
        return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_kraken_adapter.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/kraken.py KryptoWalletDashboard/backend/tests/test_kraken_adapter.py
git commit -m "feat: Kraken adapter with trade-leg pairing into swaps"
```

---

### Task 7: CoinGecko Price Client & Price Cache

**Files:**
- Create: `KryptoWalletDashboard/backend/app/prices/__init__.py`
- Create: `KryptoWalletDashboard/backend/app/prices/coingecko.py`
- Test: `KryptoWalletDashboard/backend/tests/test_coingecko_prices.py`

- [ ] **Step 1: Write the failing test**

`KryptoWalletDashboard/backend/tests/test_coingecko_prices.py`:
```python
from datetime import date
from decimal import Decimal

import responses

from app.models import PriceCache
from app.prices.coingecko import CoinGeckoPriceClient, get_or_fetch_price_chf


@responses.activate
def test_client_fetches_historical_price_in_chf():
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {"current_price": {"chf": "42000.5"}}},
        status=200,
    )

    client = CoinGeckoPriceClient()
    price = client.get_price_chf("BTC", date(2024, 1, 15))

    assert price == Decimal("42000.5")
    assert responses.calls[0].request.params["date"] == "15-01-2024"


def test_client_returns_none_for_unknown_asset():
    client = CoinGeckoPriceClient()
    assert client.get_price_chf("NOT-A-COIN", date(2024, 1, 15)) is None


@responses.activate
def test_get_or_fetch_price_chf_uses_cache_on_second_call(db_session):
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {"current_price": {"chf": "42000.5"}}},
        status=200,
    )
    client = CoinGeckoPriceClient()

    first = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))
    second = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))

    assert first == Decimal("42000.5")
    assert second == Decimal("42000.5")
    assert len(responses.calls) == 1
    assert db_session.query(PriceCache).count() == 1


@responses.activate
def test_get_or_fetch_price_chf_returns_none_and_does_not_cache_on_missing_price(db_session):
    responses.add(
        responses.GET,
        "https://api.coingecko.com/api/v3/coins/bitcoin/history",
        json={"market_data": {}},
        status=200,
    )
    client = CoinGeckoPriceClient()

    result = get_or_fetch_price_chf(db_session, client, "BTC", date(2024, 1, 15))

    assert result is None
    assert db_session.query(PriceCache).count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_coingecko_prices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.prices'`.

- [ ] **Step 3: Implement `app/prices/coingecko.py`**

`KryptoWalletDashboard/backend/app/prices/__init__.py`: empty file.

`KryptoWalletDashboard/backend/app/prices/coingecko.py`:
```python
from datetime import date
from decimal import Decimal

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceCache

COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "XBT": "bitcoin",
    "ETH": "ethereum",
}


class CoinGeckoPriceClient:
    BASE_URL = "https://api.coingecko.com/api/v3"

    def get_price_chf(self, asset: str, on_date: date) -> Decimal | None:
        coingecko_id = COINGECKO_ID_MAP.get(asset.upper())
        if coingecko_id is None:
            return None
        response = requests.get(
            f"{self.BASE_URL}/coins/{coingecko_id}/history",
            params={"date": on_date.strftime("%d-%m-%Y"), "localization": "false"},
            timeout=10,
        )
        response.raise_for_status()
        price = response.json().get("market_data", {}).get("current_price", {}).get("chf")
        return Decimal(str(price)) if price is not None else None


def get_or_fetch_price_chf(
    session: Session, client: CoinGeckoPriceClient, asset: str, on_date: date
) -> Decimal | None:
    cached = session.execute(
        select(PriceCache).where(PriceCache.asset == asset, PriceCache.date == on_date)
    ).scalar_one_or_none()
    if cached is not None:
        return cached.price_chf

    price = client.get_price_chf(asset, on_date)
    if price is not None:
        session.add(PriceCache(asset=asset, date=on_date, price_chf=price))
        session.commit()
    return price
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_coingecko_prices.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/prices/__init__.py KryptoWalletDashboard/backend/app/prices/coingecko.py KryptoWalletDashboard/backend/tests/test_coingecko_prices.py
git commit -m "feat: CoinGecko historical CHF price client with DB cache"
```

---

### Task 8: Sync Orchestration

**Files:**
- Create: `KryptoWalletDashboard/backend/app/sync.py`
- Test: `KryptoWalletDashboard/backend/tests/test_sync.py`

**Behavior:** for each adapter — look up its `SyncState`, fetch transactions since `last_synced_at`, skip ones already persisted (by `source_name`+`account_label`+`external_id`), price-enrich, persist, update `SyncState`. A failing adapter records `last_error` and does **not** stop the loop.

- [ ] **Step 1: Write the failing test**

`KryptoWalletDashboard/backend/tests/test_sync.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.schemas import NormalizedTransaction
from app.sync import sync_all


class FakePriceClient:
    def __init__(self, price=Decimal("100")):
        self.price = price

    def get_price_chf(self, asset, on_date):
        return self.price


class FakeAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "fake"

    def __init__(self, account_label, transactions=None, error=None):
        super().__init__(account_label)
        self._transactions = transactions or []
        self._error = error
        self.received_since = "not-called"

    def fetch_transactions(self, since):
        self.received_since = since
        if self._error is not None:
            raise self._error
        return self._transactions


def _tx(external_id, amount="1", tx_type="transfer_in", asset="FAKE"):
    return NormalizedTransaction(
        timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        source_type="chain",
        source_name="fake",
        account_label="main",
        tx_type=tx_type,
        asset=asset,
        amount=Decimal(amount),
        external_id=external_id,
        raw_json="{}",
    )


def test_sync_persists_new_transactions_and_enriches_price(db_session):
    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    reports = sync_all(db_session, [adapter], FakePriceClient(Decimal("100")))

    assert reports == [{"source_name": "fake", "account_label": "main", "status": "ok", "new_transactions": 1}]
    saved = db_session.query(Transaction).one()
    assert saved.external_id == "t1"
    assert saved.price_chf == Decimal("100")
    assert saved.value_chf == Decimal("100")


def test_sync_skips_already_persisted_transactions(db_session):
    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter], FakePriceClient())
    reports = sync_all(db_session, [FakeAdapter("main", transactions=[_tx("t1")])], FakePriceClient())

    assert reports[0]["new_transactions"] == 0
    assert db_session.query(Transaction).count() == 1


def test_sync_uses_last_synced_at_as_since_on_second_run(db_session):
    adapter1 = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter1], FakePriceClient())

    adapter2 = FakeAdapter("main", transactions=[])
    sync_all(db_session, [adapter2], FakePriceClient())

    state = db_session.query(SyncState).one()
    assert adapter2.received_since == state.last_synced_at


def test_sync_records_error_and_continues_with_other_adapters(db_session):
    failing = FakeAdapter("broken", error=RuntimeError("API down"))
    working = FakeAdapter("main", transactions=[_tx("t1")])

    reports = sync_all(db_session, [failing, working], FakePriceClient())

    assert reports[0]["status"] == "error"
    assert "API down" in reports[0]["error"]
    assert reports[1]["status"] == "ok"
    assert db_session.query(Transaction).count() == 1

    failing_state = db_session.query(SyncState).filter_by(account_label="broken").one()
    assert failing_state.last_error == "API down"


def test_sync_handles_missing_price_gracefully(db_session):
    class NonePriceClient:
        def get_price_chf(self, asset, on_date):
            return None

    adapter = FakeAdapter("main", transactions=[_tx("t1")])
    sync_all(db_session, [adapter], NonePriceClient())

    saved = db_session.query(Transaction).one()
    assert saved.price_chf is None
    assert saved.value_chf is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sync'`.

- [ ] **Step 3: Implement `app/sync.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import TransactionAdapter
from app.models import SyncState, Transaction
from app.prices.coingecko import get_or_fetch_price_chf


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
        since = state.last_synced_at
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

            state.last_synced_at = datetime.now(timezone.utc)
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_sync.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/sync.py KryptoWalletDashboard/backend/tests/test_sync.py
git commit -m "feat: sync orchestration with incremental sync and per-adapter error isolation"
```

---

### Task 9: Portfolio Calculation

**Files:**
- Create: `KryptoWalletDashboard/backend/app/portfolio.py`
- Test: `KryptoWalletDashboard/backend/tests/test_portfolio.py`

**Behavior:** sum inflows (`transfer_in`, `staking_reward`, `buy`, and the `asset` side of `swap`) minus outflows (`transfer_out`, `fee`, `sell`, and the `counter_asset` side of `swap`), minus any fee paid in that asset. Assets with zero net balance are omitted. `value_chf` uses the most recent per-unit price seen for that asset among priced transactions.

- [ ] **Step 1: Write the failing test**

`KryptoWalletDashboard/backend/tests/test_portfolio.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

from app.models import Transaction
from app.portfolio import compute_portfolio


def _tx(**overrides):
    kwargs = dict(
        timestamp=datetime.now(timezone.utc),
        source_type="chain",
        source_name="bitcoin",
        account_label="main",
        tx_type="transfer_in",
        asset="BTC",
        amount=Decimal("1"),
        external_id="id",
        raw_json="{}",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_incoming_and_outgoing_transfers_net_out(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1"), price_chf=Decimal("100"), value_chf=Decimal("100")))
    db_session.add(_tx(external_id="2", tx_type="transfer_out", amount=Decimal("0.4")))
    db_session.commit()

    portfolio = compute_portfolio(db_session)

    assert len(portfolio) == 1
    assert portfolio[0]["asset"] == "BTC"
    assert portfolio[0]["amount"] == Decimal("0.6")
    assert portfolio[0]["price_chf"] == Decimal("100")
    assert portfolio[0]["value_chf"] == Decimal("60")


def test_zero_balance_asset_is_omitted(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1")))
    db_session.add(_tx(external_id="2", tx_type="transfer_out", amount=Decimal("1")))
    db_session.commit()

    assert compute_portfolio(db_session) == []


def test_swap_moves_balance_between_assets(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="swap",
            asset="BTC",
            amount=Decimal("0.01"),
            counter_asset="ZEUR",
            counter_amount=Decimal("500"),
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["BTC"]["amount"] == Decimal("0.01")
    assert portfolio["ZEUR"]["amount"] == Decimal("-500")


def test_fee_reduces_balance_of_fee_asset(db_session):
    db_session.add(
        _tx(
            external_id="1",
            tx_type="transfer_out",
            asset="ETH",
            amount=Decimal("1"),
            fee_amount=Decimal("0.001"),
            fee_asset="ETH",
        )
    )
    db_session.commit()

    portfolio = {row["asset"]: row for row in compute_portfolio(db_session)}
    assert portfolio["ETH"]["amount"] == Decimal("-1.001")


def test_missing_price_yields_none_value(db_session):
    db_session.add(_tx(external_id="1", tx_type="transfer_in", amount=Decimal("1"), price_chf=None, value_chf=None))
    db_session.commit()

    portfolio = compute_portfolio(db_session)
    assert portfolio[0]["price_chf"] is None
    assert portfolio[0]["value_chf"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_portfolio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.portfolio'`.

- [ ] **Step 3: Implement `app/portfolio.py`**

```python
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

INFLOW_TYPES = {"transfer_in", "staking_reward", "buy"}
OUTFLOW_TYPES = {"transfer_out", "fee", "sell"}


def compute_portfolio(session: Session) -> list[dict]:
    rows = session.execute(select(Transaction)).scalars().all()

    balances: dict[str, Decimal] = {}
    latest_price_per_unit: dict[str, Decimal] = {}

    def add_balance(asset: str, delta: Decimal) -> None:
        balances[asset] = balances.get(asset, Decimal(0)) + delta

    for tx in rows:
        if tx.tx_type in INFLOW_TYPES:
            add_balance(tx.asset, tx.amount)
        elif tx.tx_type in OUTFLOW_TYPES:
            add_balance(tx.asset, -tx.amount)
        elif tx.tx_type == "swap":
            add_balance(tx.asset, tx.amount)
            if tx.counter_asset is not None:
                add_balance(tx.counter_asset, -(tx.counter_amount or Decimal(0)))

        if tx.fee_amount and tx.fee_asset and tx.tx_type != "fee":
            add_balance(tx.fee_asset, -tx.fee_amount)

        if tx.value_chf is not None and tx.amount != 0:
            latest_price_per_unit[tx.asset] = tx.value_chf / tx.amount

    portfolio = []
    for asset, amount in balances.items():
        if amount == 0:
            continue
        price = latest_price_per_unit.get(asset)
        portfolio.append(
            {
                "asset": asset,
                "amount": amount,
                "price_chf": price,
                "value_chf": price * amount if price is not None else None,
            }
        )
    return portfolio
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_portfolio.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/portfolio.py KryptoWalletDashboard/backend/tests/test_portfolio.py
git commit -m "feat: portfolio balance calculation from transactions"
```

---

### Task 10: CSV Export

**Files:**
- Create: `KryptoWalletDashboard/backend/app/csv_export.py`
- Test: `KryptoWalletDashboard/backend/tests/test_csv_export.py`

- [ ] **Step 1: Write the failing test**

`KryptoWalletDashboard/backend/tests/test_csv_export.py`:
```python
import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.csv_export import export_csv
from app.models import Transaction


def _tx(**overrides):
    kwargs = dict(
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
    kwargs.update(overrides)
    return Transaction(**kwargs)


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_export_includes_header_and_all_columns(db_session):
    db_session.add(_tx())
    db_session.commit()

    rows = _rows(export_csv(db_session))

    assert len(rows) == 1
    row = rows[0]
    assert row["Chain/Boerse"] == "bitcoin"
    assert row["Wallet"] == "main"
    assert row["Typ"] == "transfer_in"
    assert row["Asset"] == "BTC"
    assert row["Menge"] == "1"
    assert row["Kurs CHF"] == "50000"
    assert row["Wert CHF"] == "50000"
    assert row["Referenz"] == "id1"


def test_export_filters_by_date_range(db_session):
    db_session.add(_tx(external_id="old", timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc)))
    db_session.add(_tx(external_id="new", timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc)))
    db_session.commit()

    rows = _rows(
        export_csv(
            db_session,
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 12, 31, tzinfo=timezone.utc),
        )
    )

    assert [r["Referenz"] for r in rows] == ["new"]


def test_export_filters_by_source_name_tx_type_and_account_label(db_session):
    db_session.add(_tx(external_id="a", source_name="bitcoin", tx_type="transfer_in", account_label="main"))
    db_session.add(_tx(external_id="b", source_name="ethereum", tx_type="transfer_out", account_label="savings"))
    db_session.commit()

    rows = _rows(export_csv(db_session, source_name="bitcoin"))
    assert [r["Referenz"] for r in rows] == ["a"]

    rows = _rows(export_csv(db_session, tx_type="transfer_out"))
    assert [r["Referenz"] for r in rows] == ["b"]

    rows = _rows(export_csv(db_session, account_label="savings"))
    assert [r["Referenz"] for r in rows] == ["b"]


def test_export_leaves_missing_price_fields_blank(db_session):
    db_session.add(_tx(price_chf=None, value_chf=None))
    db_session.commit()

    rows = _rows(export_csv(db_session))
    assert rows[0]["Kurs CHF"] == ""
    assert rows[0]["Wert CHF"] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest tests/test_csv_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.csv_export'`.

- [ ] **Step 3: Implement `app/csv_export.py`**

```python
import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction

COLUMNS = [
    "Datum",
    "Chain/Boerse",
    "Wallet",
    "Typ",
    "Asset",
    "Menge",
    "Kurs CHF",
    "Wert CHF",
    "Gebuehr",
    "Gebuehr Asset",
    "Referenz",
]


def export_csv(
    session: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    source_name: str | None = None,
    tx_type: str | None = None,
    account_label: str | None = None,
) -> str:
    query = select(Transaction).order_by(Transaction.timestamp)
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
    rows = session.execute(query).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for tx in rows:
        writer.writerow(
            [
                tx.timestamp.isoformat(),
                tx.source_name,
                tx.account_label,
                tx.tx_type,
                tx.asset,
                str(tx.amount),
                str(tx.price_chf) if tx.price_chf is not None else "",
                str(tx.value_chf) if tx.value_chf is not None else "",
                str(tx.fee_amount) if tx.fee_amount is not None else "",
                tx.fee_asset or "",
                tx.external_id,
            ]
        )
    return output.getvalue()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/pytest tests/test_csv_export.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add KryptoWalletDashboard/backend/app/csv_export.py KryptoWalletDashboard/backend/tests/test_csv_export.py
git commit -m "feat: filterable CSV export"
```

---

### Task 11: FastAPI Endpoints

**Files:**
- Create: `KryptoWalletDashboard/backend/app/adapters/factory.py`
- Create: `KryptoWalletDashboard/backend/app/main.py`
- Test: `KryptoWalletDashboard/backend/tests/test_api.py`

- [ ] **Step 1: Implement the adapter factory (no test — thin config wiring, exercised indirectly through Task 12's manual smoke test)**

`KryptoWalletDashboard/backend/app/adapters/factory.py`:
```python
from app import config
from app.adapters.base import TransactionAdapter
from app.adapters.bitcoin import BitcoinAdapter
from app.adapters.ethereum import EthereumAdapter
from app.adapters.kraken import KrakenAdapter


def build_adapters_from_config() -> list[TransactionAdapter]:
    adapters: list[TransactionAdapter] = []
    for wallet in config.BITCOIN_WALLETS:
        adapters.append(BitcoinAdapter(account_label=wallet.label, address=wallet.address))
    for wallet in config.ETHEREUM_WALLETS:
        adapters.append(
            EthereumAdapter(
                account_label=wallet.label,
                address=wallet.address,
                api_key=config.ETHERSCAN_API_KEY,
            )
        )
    if config.KRAKEN_API_KEY and config.KRAKEN_API_SECRET:
        adapters.append(
            KrakenAdapter(
                account_label="kraken-main",
                api_key=config.KRAKEN_API_KEY,
                api_secret=config.KRAKEN_API_SECRET,
            )
        )
    return adapters
```

- [ ] **Step 2: Write the failing API tests**

`KryptoWalletDashboard/backend/tests/test_api.py`:
```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 4: Implement `app/main.py`**

```python
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
from app.schemas import TransactionOut
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


@app.get("/api/portfolio")
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest tests/test_api.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the full test suite**

Run: `.venv/Scripts/pytest -v`
Expected: PASS, all tests across all files green (approximately 40 tests).

- [ ] **Step 7: Commit**

```bash
git add KryptoWalletDashboard/backend/app/adapters/factory.py KryptoWalletDashboard/backend/app/main.py KryptoWalletDashboard/backend/tests/test_api.py
git commit -m "feat: FastAPI endpoints for sync, portfolio, transactions and CSV export"
```

---

### Task 12: Setup Documentation & Manual Smoke Test

**Files:**
- Create: `KryptoWalletDashboard/backend/README.md`

- [ ] **Step 1: Write the backend README**

`KryptoWalletDashboard/backend/README.md`:
```markdown
# Krypto-Wallet-Dashboard – Backend

## Setup

1. `python -m venv .venv`
2. `.venv/Scripts/pip install -r requirements.txt`
3. `cp .env.example .env` und die eigenen Wallet-Adressen / API-Keys eintragen
   (Kraken-Key **muss** read-only sein - keine Trade-/Auszahlungsrechte!)
4. Datenbank einmalig anlegen: `.venv/Scripts/python -m app.init_db`

## Server starten

```bash
.venv/Scripts/uvicorn app.main:app --reload
```

Läuft danach auf `http://127.0.0.1:8000`.

## Manueller Smoke-Test

1. `curl -X POST http://127.0.0.1:8000/api/sync` - stößt Sync für alle konfigurierten
   Wallets/Accounts an, gibt pro Quelle `status: ok` oder `status: error` zurück
2. `curl http://127.0.0.1:8000/api/portfolio` - aktuelle Bestände
3. `curl http://127.0.0.1:8000/api/transactions` - alle Transaktionen
4. `curl http://127.0.0.1:8000/api/export -o test.csv` - CSV-Export prüfen

## Tests

```bash
.venv/Scripts/pytest -v
```

Alle Tests laufen gegen gemockte HTTP-Antworten (`responses`) und eine
In-Memory-SQLite-DB - keine echten API-Calls, keine echten Credentials nötig.
```

- [ ] **Step 2: Commit**

```bash
git add KryptoWalletDashboard/backend/README.md
git commit -m "docs: backend setup and smoke test instructions"
```

- [ ] **Step 3: Manual verification (requires real, read-only credentials in `.env`)**

Follow the README's "Manueller Smoke-Test" section against your own wallet
addresses / read-only Kraken key. Confirm:
- `/api/sync` reports `status: ok` for each configured source
- `/api/portfolio` shows plausible current balances
- `/api/transactions` lists real transactions with sensible CHF values
- `/api/export` produces a valid CSV openable in Excel/LibreOffice

---

## Self-Review Notes

- **Spec coverage:** Chains covered — Bitcoin, Ethereum (Phase 1 subset of the 6). Kraken covers the exchange side. Tx types `buy`/`sell`/`swap`/`staking_reward`/`transfer_in`/`transfer_out`/`fee` are all representable in the schema and handled by `portfolio.py` and `csv_export.py`, even though only a subset is actually produced by the Phase 1 adapters (chain adapters only emit transfers; Kraken emits transfer_in/out, staking_reward, swap). CHF pricing via CoinGecko: done (Task 7-8). Filterable transaction list + CSV export with Zeitraum/Chain/Typ/Wallet filters: done (Tasks 10-11). Portfolio overview: done (Task 9). Local-only, read-only credentials, `.gitignore`: done (Task 1, plus existing `KryptoWalletDashboard/.gitignore`). ESTV year-end prices and Phase 2/3 adapters: explicitly deferred, noted at top of plan.
- **Placeholder scan:** no TBD/TODO; every step has complete, runnable code.
- **Type consistency:** `NormalizedTransaction` (Task 3) fields match what `sync.py` (Task 8) reads and what `Transaction` (Task 2) stores; `TransactionOut` (Task 3) field names match `Transaction` model columns used by `/api/transactions` (Task 11); `compute_portfolio()`'s return dict keys (`asset`, `amount`, `price_chf`, `value_chf`) match what `/api/portfolio` returns and what a future frontend plan will consume.
