# Phase 3 – React-Frontend – Design

Datum: 2026-08-05

## Zweck

Separates React-Frontend für das Krypto-Wallet-Dashboard, das den bereits
vollständig fertigen Backend-Stack (Bitcoin, 6 EVM-Chains, Kraken, Coinbase,
MEXC, Binance) für die Schweizer Steuererklärung nutzbar macht: Portfolio-
Übersicht, Transaktionsliste mit Filtern, manueller Sync-Trigger, CSV-Export
mit Datumsbereich. Macht das Backend erstmals tatsächlich benutzbar (bisher
nur per `curl` testbar).

## Tech-Stack (mit Nutzer bestätigt)

- **TypeScript** (Typsicherheit passend zu den Pydantic-Schemas im Backend)
- **Vite** als Build-Tool (Standard für React+TypeScript-Projekte, schnelles
  Dev-Setup, kein CRA - das ist deprecated)
- **React Router** für die drei Seiten (Übersicht/Transaktionen/Sync)
- **Tailwind CSS** für Styling (utility-first, kein separates
  Komponenten-Kit nötig für ein Dashboard mit Sidebar/Tabellen/Filtern)
- **recharts** für die Portfolio-Verteilung (Kreisdiagramm) auf der
  Übersichtsseite
- **Plain `fetch` + React State** für die Backend-Anbindung (kein
  TanStack Query - für ein lokal laufendes Tool mit 4 Endpunkten
  überdimensioniert)
- **npm** als Package-Manager (Standard, kein zusätzliches Tooling nötig)

## Bestehende Backend-API (bereits vorhanden, keine Änderung nötig außer CORS)

- `POST /api/sync` → `{"results": [...]}` (pro Adapter Status `ok`/`error`)
- `GET /api/portfolio` → `[{asset, amount, price_chf, value_chf}]`
- `GET /api/transactions?start&end&source_name&tx_type&account_label` →
  Liste von Transaktionen (`id, timestamp, source_type, source_name,
  account_label, tx_type, asset, amount, counter_asset, counter_amount,
  price_chf, value_chf, fee_amount, fee_asset, external_id`)
- `GET /api/export?<gleiche Filter>` → CSV-Datei-Download
  (`Content-Disposition: attachment`)

**Nötige Backend-Änderung:** FastAPI hat aktuell **keine CORS-Middleware**.
Der Vite-Dev-Server läuft auf einem anderen Port (`localhost:5173`) als das
Backend (`127.0.0.1:8000`) - ohne CORS blockt der Browser jeden Fetch-Aufruf.
Ergänzt wird `CORSMiddleware` in `app/main.py`, beschränkt auf
`http://localhost:5173`/`http://127.0.0.1:5173` (lokale Dev-Server-Origins;
das Tool ist explizit nur für lokalen Gebrauch gedacht, siehe bestehende
README-Warnung "keine Authentifizierung, nur lokal betreiben" - eine
offene CORS-Policy wäre hier ein echtes Sicherheitsrisiko, eine auf
`localhost` beschränkte ist unkritisch).

## Seitenstruktur (Sidebar-Navigation, bereits im initialen Brainstorming
## festgelegt)

Drei Seiten, erreichbar über eine feste Sidebar links:

1. **Übersicht** (`/`) - aktuelle Bestände pro Asset (Tabelle: Asset, Menge,
   Kurs CHF, Wert CHF), Gesamt-Portfoliowert CHF oben, Kreisdiagramm
   (recharts `PieChart`) der Wertverteilung nach Asset darunter/daneben.
   Datenquelle: `GET /api/portfolio`.
2. **Transaktionen** (`/transactions`) - Tabelle aller Transaktionen,
   Filterleiste oben (Datumsbereich von/bis, Quelle/Chain-Dropdown,
   Transaktionstyp-Dropdown, Wallet/Konto-Dropdown - exakt die im initialen
   Brainstorming festgelegten Filter: "Chain/Quelle, Transaktionstyp,
   Wallet/Adresse"). "CSV exportieren"-Button oben rechts, der die aktuell
   aktiven Filter an `GET /api/export` weiterreicht und den Download über
   den Browser auslöst (Response-Blob → `<a download>`-Trick, kein
   zusätzliches Paket nötig). Datenquelle: `GET /api/transactions` mit
   denselben Filterparametern.
3. **Sync** (`/sync`) - ein Button "Jetzt synchronisieren", der
   `POST /api/sync` auslöst; während des Laufs Ladeanzeige (der Aufruf kann
   je nach Anzahl konfigurierter Quellen mehrere Sekunden dauern); danach
   Ergebnisliste pro Quelle (Name, Status `ok`/`error`, bei `error` die
   Fehlermeldung) - direkt aus der `results`-Antwort von `/api/sync`
   gerendert, keine zusätzliche Logik nötig.

Die Dropdown-Optionen für "Quelle"/"Transaktionstyp"/"Konto" in der
Filterleiste werden **client-seitig aus den bereits geladenen Transaktionen
abgeleitet** (`Array.from(new Set(transactions.map(...)))`), nicht über
einen eigenen Backend-Endpunkt - es gibt keinen `/api/sources`-Endpunkt und
einen neuen nur für Dropdown-Optionen zu bauen wäre für den Umfang dieses
Tools unnötig (YAGNI). Einschränkung: die Dropdown-Optionen zeigen nur
Werte, die in der *aktuell ungefilterten* Transaktionsmenge vorkommen -
akzeptabel für ein Ein-Nutzer-Lokal-Tool.

## Fehlerbehandlung & Ladezustände

Jede Seite zeigt einen einfachen Ladeindikator während des initialen
Fetches und eine Fehlermeldung (Text, keine Toast-Bibliothek), falls der
Fetch fehlschlägt (z.B. Backend nicht gestartet) - mit Hinweis, dass das
Backend unter `http://127.0.0.1:8000` laufen muss.

## Beträge & Formatierung

CHF-Beträge werden über `Intl.NumberFormat("de-CH", {style: "currency",
currency: "CHF"})` formatiert (Schweizer Zahlenformat: Apostroph als
Tausendertrennzeichen). Krypto-Mengen (potenziell viele Nachkommastellen,
z.B. Satoshi-Beträge) werden ohne Rundung als String direkt aus der API
übernommen (Backend liefert `Decimal` bereits als exakten String über
Pydantics JSON-Encoding) - keine JS-`Number`-Konvertierung, um
Fließkomma-Rundungsfehler bei sehr kleinen/großen Krypto-Beträgen zu
vermeiden.

## Was explizit NICHT Teil dieser Phase ist

- Keine Authentifizierung/Login (Tool ist explizit nur für lokalen Gebrauch
  gedacht, wie im Backend-README dokumentiert)
- Kein automatischer/periodischer Sync (nur manueller Button, wie im
  initialen Brainstorming festgelegt: "lokale Datenbank + manueller
  Sync-Button")
- Keine Bearbeitung/Löschung von Transaktionen über die UI (reine
  Leseansicht + Sync-Trigger)
- Kein Production-Build/Deployment-Setup über `npm run build` hinaus (Tool
  läuft lokal via `npm run dev`, kein Hosting geplant)

## Offene Punkte für die Umsetzungsplanung

Keine - Design wurde durchgesprochen und mit dem Nutzer bestätigt
(TypeScript, Tailwind, recharts, plain fetch).
