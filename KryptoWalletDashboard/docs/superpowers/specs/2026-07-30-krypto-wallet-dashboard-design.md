# Krypto-Wallet-Dashboard – Design

Datum: 2026-07-30

## Zweck

Ein lokal laufendes Dashboard, das Kryptowährungs-Transaktionen (Käufe, Verkäufe,
Tausch, Staking-Erträge, Transfers, Gebühren) über mehrere Blockchains und
Börsen hinweg zusammenführt, mit dem CHF-Wert zum jeweiligen Zeitpunkt anreichert
und als CSV mit Zeitraum-/Chain-/Typ-/Wallet-Filtern exportiert. Zweck: Grundlage
für die Schweizer Steuererklärung (Einkommens- und Vermögenssteuerwerte).

## Umfang

**Chains (6, on-chain, nur öffentliche Adressen, keine Private Keys):**
Bitcoin, Ethereum, weitere EVM-Chains (z.B. Polygon, BSC, Arbitrum – ein
parametrisierter Adapter), Solana, Cardano, VeChain.

**Börsen (4, via read-only API-Key):**
MEXC, Binance, Kraken, Coinbase.

Mehrere Wallet-Adressen pro Chain werden unterstützt.

Alle 6 Chains sind von Anfang an architektonisch vorgesehen, werden aber in
Phasen implementiert (siehe unten).

## Betriebsart & Sicherheit

- Läuft ausschliesslich **lokal** auf dem Rechner des Nutzers (kein Hosting).
- Börsen-API-Keys werden **read-only** angelegt (keine Trade-/Auszahlungsrechte)
  – das ist eine harte Anforderung, nicht optional.
- Keys liegen in einer lokalen `.env`/Config-Datei, die via `.gitignore` nie
  ins Repository gelangt.
- Es werden nie Private Keys benötigt oder gespeichert, nur öffentliche
  Wallet-Adressen und read-only API-Keys.

## Architektur

```
10 Adapter (6 Chains + 4 Börsen, gemeinsames Interface fetch_transactions)
        │
        ▼
Sync-Job (manuell ausgelöst) – normalisiert Transaktionen,
        holt fehlende CHF-Kurse (CoinGecko + ESTV-Jahresendkurse)
        │
        ▼
SQLite-DB (lokale Datei, Transaktionen + Kurse gecacht)
        │
        ▼
FastAPI-Backend (REST-Endpunkte: Portfolio / Transaktionen / Export)
        │
        ▼
React-Frontend (Sidebar-Navigation: Portfolio | Transaktionen | Export,
        läuft lokal im Browser)
```

- **Backend:** Python, FastAPI.
- **Frontend:** React (TypeScript), spricht mit dem Backend über REST.
- **Speicherung:** SQLite-Datei lokal im Projektverzeichnis (gitignored).
- **Sync:** manuell per Button ausgelöst, inkrementell (pro Quelle nur seit
  letztem erfolgreichen Sync).

## Datenmodell

### Tabelle `transactions`

| Feld | Beschreibung |
|---|---|
| `id` | Primärschlüssel |
| `timestamp` | Zeitpunkt der Transaktion (UTC) |
| `source_type` | `chain` oder `exchange` |
| `source_name` | z.B. `bitcoin`, `ethereum`, `kraken` |
| `account_label` | welche Wallet-Adresse / welcher Börsen-Account |
| `tx_type` | `buy`, `sell`, `swap`, `staking_reward`, `transfer_in`, `transfer_out`, `fee` |
| `asset` | z.B. `ETH` |
| `amount` | Menge |
| `counter_asset` | Gegenwert-Asset bei Tausch (nullable) |
| `counter_amount` | Gegenwert-Menge bei Tausch (nullable) |
| `price_chf` | CHF-Kurs pro Einheit zum Transaktionszeitpunkt |
| `value_chf` | `amount * price_chf` |
| `fee_amount` / `fee_asset` / `fee_value_chf` | Gebühren |
| `external_id` / `tx_hash` | zur Nachverfolgung und Duplikatserkennung |
| `raw_json` | Rohdaten der Quelle (Debugging) |

### Tabelle `price_cache`

CHF-Tageskurse pro Asset (Quelle: CoinGecko), damit derselbe Tag/Asset nicht
mehrfach abgefragt wird.

### Tabelle `year_end_prices`

ESTV-Jahresendkurse pro Asset/Jahr, für den Vermögenssteuerwert am 31.12.

### Portfolio-Übersicht

Wird aus den Transaktionen berechnet (Summe Zu-/Abgänge je Asset), kein
separates manuelles Pflegen von Beständen.

## Kursdaten

- **CoinGecko API**: historische Tageskurse in CHF, für den Wert jeder
  einzelnen Transaktion (Gewinn/Verlust-Berechnung).
- **ESTV-Kursliste** (Eidg. Steuerverwaltung): offizielle Jahresendkurse, für
  den Vermögenssteuerwert am 31.12. je Asset.

## UI

Sidebar-Navigation mit drei Bereichen:

1. **Portfolio** – aktueller Bestand je Coin/Chain, aktueller CHF-Wert,
   grobe Gewinn/Verlust-Übersicht.
2. **Transaktionen** – filterbare, sortierbare Tabelle. Filter: Zeitraum,
   Chain/Quelle, Transaktionstyp, Wallet/Adresse.
3. **Export** – CSV-Export der (gefilterten) Transaktionen.

### CSV-Export-Format

Generisches, vollständiges CSV, eine Zeile pro Transaktion:
Datum, Chain/Börse, Wallet, Typ, Asset, Menge, Kurs CHF, Wert CHF, Gebühr,
Tx-Hash/Referenz. Respektiert die aktuell gesetzten Filter (Zeitraum,
Chain/Quelle, Typ, Wallet).

## Adapter & Phasenplan

Alle Adapter implementieren dieselbe Schnittstelle (`fetch_transactions`),
werden aber in drei Phasen gebaut:

**Phase 1 – Fundament** (beweist die Architektur end-to-end inkl. komplettem UI):
- Bitcoin (Blockstream/Mempool.space API)
- Ethereum (Etherscan API)
- Kraken (offizielle REST-API, read-only Key)

**Phase 2 – Restliche EVM-Chains & Börsen:**
- Weitere EVM-Chains (Polygon, BSC, Arbitrum, ...) über einen parametrisierten
  Etherscan-artigen Adapter
- Binance, Coinbase, MEXC

**Phase 3 – Nicht-EVM-Sonderfälle** (jeweils eigenes API-Format):
- Solana (Solana RPC / Solscan)
- Cardano (Blockfrost API)
- VeChain (VeChainStats API)

## Fehlerbehandlung

- Jeder Adapter läuft isoliert: schlägt einer fehl (z.B. API-Rate-Limit),
  blockiert das nicht die anderen Quellen. Fehler werden im UI als
  "Sync fehlgeschlagen für <Quelle>" angezeigt.
- Fehlende Kursdaten für eine Transaktion: die Transaktion wird trotzdem
  angezeigt, mit Markierung "Preis fehlt", und aus Steuer-Summen
  ausgeklammert bis der Kurs nachträglich geladen werden konnte.
- Sync ist inkrementell (pro Quelle nur seit letztem erfolgreichen Sync),
  um API-Limits zu schonen.

## Tests

- Unit-Tests je Adapter mit aufgezeichneten/gemockten API-Antworten (keine
  Live-API-Calls in automatisierten Tests).
- Unit-Tests für Preis-Anreicherung und Normalisierung der Transaktionen.
- Unit-Tests für CSV-Export (korrekte Spalten, korrekte Filterung).
- Manueller End-to-End-Check gegen echte Wallets/Accounts nach Phase 1.

## Offene Punkte für die Umsetzungsplanung

Keine – Design wurde vollständig durchgesprochen und bestätigt. Die
Implementierung erfolgt phasenweise (siehe Adapter & Phasenplan); der erste
Implementierungsplan sollte sich auf Phase 1 konzentrieren.
