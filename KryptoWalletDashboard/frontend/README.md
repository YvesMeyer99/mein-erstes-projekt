# Krypto-Wallet-Dashboard – Frontend

React-Frontend für das Krypto-Wallet-Dashboard-Backend.

## Setup

1. `npm install`
2. Backend muss laufen (siehe `../backend/README.md`, Standard-Adresse
   `http://127.0.0.1:8000`)
3. `npm run dev`

Läuft danach auf `http://localhost:5173`.

## Seiten

- **Übersicht** (`/`) – aktuelle Bestände, CHF-Gesamtwert,
  Verteilungs-Diagramm
- **Transaktionen** (`/transactions`) – Tabelle mit Filtern (Datum,
  Quelle, Typ, Konto), CSV-Export
- **Sync** (`/sync`) – manueller Sync-Trigger mit Ergebnis pro Quelle
- **Konfiguration** (`/konfiguration`) – Wallet-Adressen und API-Keys
  aus der `.env` bearbeiten; Speichern wirkt sofort, ohne Backend-Neustart
- **Accounts** (`/accounts`) – alle Accounts in der DB, gezielt einzelne
  löschen (unabhängig von der `.env`)

## Tests

```bash
npm test
```

## Build

```bash
npm run build
```
