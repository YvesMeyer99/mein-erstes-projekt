# Krypto-Wallet-Dashboard – Backend

## Setup

1. `python -m venv .venv`
2. `.venv/Scripts/pip install -r requirements.txt`
3. `cp .env.example .env` und die eigenen Wallet-Adressen / API-Keys eintragen
   (Kraken-Key **muss** read-only sein - keine Trade-/Auszahlungsrechte!)
4. Datenbank einmalig anlegen: `.venv/Scripts/python -m app.init_db`

## Unterstützte EVM-Chains

Seit Phase 2a werden neben Ethereum automatisch fünf weitere EVM-Chains
für dieselbe(n) in `ETHEREUM_ADDRESSES` konfigurierte(n) Adresse(n)
mitsynchronisiert - keine zusätzliche Konfiguration nötig:

- Ethereum
- Optimism
- BNB Smart Chain (BSC)
- Polygon
- Base
- Arbitrum One

Alle sechs laufen über Etherscans vereinheitlichte Multi-Chain-API mit
demselben `ETHERSCAN_API_KEY`. Sowohl native Coin-Transfers (ETH, BNB,
MATIC, ...) als auch ERC-20-Token-Transfers (z.B. USDT, USDC) werden auf
allen sechs Chains erfasst.

## Server starten

```bash
.venv/Scripts/uvicorn app.main:app --reload
```

Läuft danach auf `http://127.0.0.1:8000`. `uvicorn`'s CLI default host is `127.0.0.1` (localhost-only) — do NOT add `--host 0.0.0.0`, since this app has no authentication and is designed to run locally only.

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

## Bekannte Einschränkung: CoinGecko Free-Tier-Preishistorie

Die App nutzt CoinGecko's öffentlichen `/coins/{id}/history`-Endpoint, um
historische CHF-Preise zu Transaktionen zu ermitteln. Auf dem kostenlosen
CoinGecko-Tier liefert dieser Endpoint zuverlässig nur die Preishistorie der
letzten ca. 365 Tage; für ältere Daten kommt teils keine `market_data` zurück
oder die Anfrage schlägt fehl (z.B. 401).

Der Code fängt das ab und liefert in diesem Fall einfach `None`, ohne
abzustürzen oder den Cache zu verunreinigen. Das bedeutet aber: Transaktionen,
die älter als ca. ein Jahr sind, können in der API-Antwort und im
CSV-Export mit leerem/`null` `price_chf` erscheinen. Das ist auf dem
Free-Tier erwartetes Verhalten, kein Bug - ein bezahlter CoinGecko-Plan mit
vollem Historie-Zugriff würde das beheben.
