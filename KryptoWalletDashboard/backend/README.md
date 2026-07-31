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

## Coinbase

Zusätzlich zu Bitcoin/EVM-Chains/Kraken wird automatisch dein Coinbase-App-
Account (Retail, nicht Advanced Trade) mitsynchronisiert, sobald
`COINBASE_API_KEY_NAME` und `COINBASE_API_PRIVATE_KEY` gesetzt sind. Alle
Krypto-Konten (BTC, ETH, ...) werden automatisch erkannt - keine manuelle
Konten-Liste nötig. Fiat-Konten (EUR, CHF, USD, GBP, JPY, CAD, AUD) werden
bewusst übersprungen (auch keine Transaktions-Abfrage dafür), da sie für
die Krypto-Steuerbetrachtung nicht relevant sind und ihre Buy/Sell-Zeilen
sonst mit falschem Vorzeichen im Portfolio landen könnten.

**Wichtig beim Anlegen des API-Keys:**
- CDP Secret API Key mit **ECDSA-Schlüsseltyp** anlegen (nicht den seit
  2025 defaultmäßigen Ed25519-Key - der wird von dieser API nicht
  unterstützt).
- Nur die Lese-Scopes `wallet:accounts:read` und
  `wallet:transactions:read` vergeben - keine Trade-/Sende-/
  Auszahlungsrechte.

### Bekannte Einschränkung: ERC-20-Token werden nicht CHF-bewertet

ERC-20-Token-Transfers werden zwar vollständig erfasst (Menge, Sender/
Empfänger, Zeitstempel), aber **nicht automatisch in CHF bewertet**. Die
CHF-Preisermittlung (`COINGECKO_ID_MAP` in `app/prices/coingecko.py`) kennt
aktuell nur vier native Assets: BTC, ETH, BNB und MATIC. Für alle anderen
Token - inklusive der oben genannten Beispiele USDT und USDC - gibt es
keine Preiszuordnung. Solche Transaktionen laufen ohne Fehler durch den
Sync, erscheinen im CSV-Export aber mit leerem `Kurs CHF`/`Wert CHF` und
müssen für die Steuererklärung manuell bewertet werden.

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
