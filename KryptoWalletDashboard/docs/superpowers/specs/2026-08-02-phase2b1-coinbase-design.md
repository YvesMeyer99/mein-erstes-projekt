# Plan 2b-1 – Coinbase-Adapter – Design

Datum: 2026-08-02

## Zweck

Erste Börsen-Erweiterung von Plan 2b: ein Adapter für das Coinbase-App-
(Retail-)Konto, der Käufe, Verkäufe, Ein-/Auszahlungen und Sends/Receives
über alle Konten (BTC, ETH, EUR, ...) des Nutzers erfasst. Baut auf dem
bereits abgeschlossenen Phase-1-Backend und Plan 2a (EVM-Chains) auf.

## Umfang

**Coinbase-Produkt:** Coinbase App API (Retail/Consumer-Account), nicht
Coinbase Advanced Trade oder Coinbase Prime.

**Konten:** automatisch alle Konten des Accounts abgefragt (`GET
/v2/accounts`), keine manuelle Konten-Konfiguration nötig – jedes
zurückgelieferte Konto (pro Währung/Asset) wird einzeln nach
Transaktionen durchsucht.

## API-Recherche (Stand: 2026-08-02, via Coinbase Developer Docs)

- Basis-URL: `https://api.coinbase.com/v2`
- `GET /v2/accounts` – listet alle Konten des Nutzers (Pagination via
  `starting_after`/`limit`, Standard-Limit 25). Scope: `wallet:accounts:read`.
- `GET /v2/accounts/:account_id/transactions` – Transaktionen je Konto,
  gleiche Pagination. Scope: `wallet:transactions:read`.
- Transaktions-Felder (relevant): `id`, `type` (`buy`, `sell`, `send`,
  `receive`, `transfer`, ggf. weitere), `status`, `amount` (`{amount,
  currency}`, **vorzeichenbehaftet** – negativ = ausgehend, positiv =
  eingehend), `native_amount` (`{amount, currency}` – Fiat-Gegenwert zum
  Zeitpunkt der Transaktion, i.d.R. in der Kontowährung des Nutzers),
  `created_at`.

Quellen (zum Zeitpunkt der Recherche geprüft):
[Coinbase App API Key Authentication](https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication),
[Coinbase Accounts API](https://docs.cdp.coinbase.com/coinbase-app/track-apis/accounts),
[Coinbase Transactions API](https://docs.cdp.coinbase.com/coinbase-app/track-apis/transactions).

**Hinweis für die Umsetzung:** Coinbases API-Oberfläche ändert sich
gelegentlich (Felder, Scopes, Endpunkt-Details). Vor der Implementierung
kurz gegen die aktuelle Dokumentation prüfen, ob Endpunkt-Pfade,
Feldnamen und Pagination noch wie hier beschrieben sind.

## Authentifizierung: CDP-API-Key mit JWT (ES256)

Anders als Kraken (HMAC) nutzt Coinbase App API kurzlebige JWTs:

- Der Nutzer legt einen **CDP Secret API Key mit ECDSA-Schlüsseltyp**
  an (P-256/ES256) – **nicht** den seit 2025 defaultmäßigen Ed25519-Key,
  der für diese API explizit nicht unterstützt wird.
- Pro Request wird ein neues JWT gebaut und signiert:
  - Header: `alg=ES256`, `typ=JWT`, `kid=<API-Key-Name>` (Format
    `organizations/{org_id}/apiKeys/{key_id}`), `nonce` (zufälliger Hex-Wert).
  - Payload: `iss="cdp"`, `sub=<API-Key-Name>`, `uri="<METHODE> <Host><Pfad>"`,
    `nbf=<jetzt>`, `exp=<jetzt + 120s>`.
  - Signatur mit dem privaten EC-Schlüssel (PEM, `EC PRIVATE KEY`).
  - Request-Header: `Authorization: Bearer <JWT>`.
- **Neue Abhängigkeit:** ECDSA-JWT-Signierung braucht eine Krypto-
  Bibliothek. `PyJWT` mit dem `cryptography`-Extra (`PyJWT[crypto]`) wird
  ergänzt (bisher nicht in `requirements.txt`).
- **Neue Config-Felder** (statt einfachem Key/Secret-Paar wie bei Kraken):
  `COINBASE_API_KEY_NAME` (der volle `organizations/.../apiKeys/...`-Name)
  und `COINBASE_API_PRIVATE_KEY` (PEM-Text, mehrzeilig).

## Normalisierung

- `source_type="exchange"`, `source_name="coinbase"`.
- Betrag & Richtung: `amount.amount` ist vorzeichenbehaftet – negatives
  Vorzeichen → `transfer_out`, positives → `transfer_in`. `asset =
  amount.currency`.
- `type="buy"` → `tx_type="buy"`, `type="sell"` → `tx_type="sell"`
  (unabhängig vom Vorzeichen, da Buy/Sell-Transaktionen semantisch klarer
  sind als reine Transfers und unser Schema `buy`/`sell` bereits kennt).
- Alle anderen erkannten Typen (`send`, `receive`, `transfer`) werden
  über das Vorzeichen von `amount.amount` zu `transfer_in`/`transfer_out`
  normalisiert.
- Unbekannte/nicht abgedeckte `type`-Werte werden übersprungen – gleiches
  Muster wie beim Kraken-Adapter aus Phase 1 (dort bereits als
  akzeptiertes, dokumentiertes Verhalten reviewt).
- Nur `status="completed"` Transaktionen werden übernommen (pending/failed
  werden übersprungen, analog zu Kraken/Bitcoin/Ethereum, die jeweils nur
  abgeschlossene/bestätigte Vorgänge erfassen).
- Kein CHF-Preis-Feld direkt aus Coinbase übernommen – `native_amount` ist
  typischerweise in der Kontowährung des Nutzers (nicht zwingend CHF) und
  wird für Phase 1 ignoriert; die bestehende CoinGecko-Preisanreicherung
  (Task-übergreifend, `sync.py`) übernimmt die CHF-Bewertung wie bei allen
  anderen Quellen.
- `external_id` = Coinbase-Transaktions-`id`. Alle Coinbase-Sub-Konten
  (BTC, ETH, EUR, ...) teilen sich denselben `account_label="coinbase-main"`
  – `account_label` deckt das einzelne Sub-Konto im Uniqueness-Constraint
  also gerade nicht ab. Die reine Transaktions-ID genügt trotzdem, weil
  Coinbase-v2-Transaktions-IDs global eindeutige UUIDs sind (nicht bloss
  pro Konto eindeutig).
- Gebühren: Coinbase liefert bei `buy`/`sell` z.T. ein separates
  `fee`-Objekt; falls vorhanden wird es als `fee_amount`/`fee_asset`
  übernommen, sonst bleiben beide `None` (kein Fehler).

## Pagination

Wie bei Bitcoin/Ethereum/Kraken: `starting_after`-Cursor-basierte
Pagination, Standard-Limit 25 pro Seite, so lange folgen bis eine leere/
kürzere Seite kommt.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  API-Calls.
- JWT-Erzeugung wird isoliert getestet (Header-/Payload-Felder korrekt
  gesetzt, Signatur mit einem Test-EC-Schlüsselpaar verifizierbar).
- Buy/Sell/Send/Receive-Normalisierung, Status-Filter, Pagination,
  Multi-Konten-Iteration (mehrere Konten aus `/v2/accounts`, je eigene
  Transaktionsliste) – analog zum Testaufbau der bisherigen Adapter.

## Offene Punkte für die Umsetzungsplanung

Keine – Design wurde durchgesprochen und bestätigt. Coinbase Advanced
Trade, Coinbase Prime, Binance und MEXC bleiben eigene, spätere Pläne.
