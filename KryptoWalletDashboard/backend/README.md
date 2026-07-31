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
