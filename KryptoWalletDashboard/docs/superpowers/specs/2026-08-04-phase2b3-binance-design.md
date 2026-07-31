# Plan 2b-3 – Binance-Adapter – Design

Datum: 2026-08-04

## Zweck

Dritte Börsen-Erweiterung von Plan 2b: ein Adapter für Binance, der
Ein-/Auszahlungen automatisch sowie Trades für manuell konfigurierte
Handelspaare erfasst. Baut auf Phase 1, Plan 2a (EVM-Chains), Plan 2b-1
(Coinbase) und Plan 2b-2 (MEXC) auf. Binance (global, `binance.com` -
nicht Binance.US) wird als Quelle behandelt.

## API-Recherche (Stand: 2026-08-04, via developers.binance.com REST-API-Docs)

- Basis-URL: `https://api.binance.com`
- Auth: `X-MBX-APIKEY`-Header + `signature`-Query-Parameter =
  `HMAC-SHA256(Query-String, secretKey)`, lowercase Hex. Pflicht-
  Parameter jeder SIGNED-Anfrage: `timestamp` (ms), optional
  `recvWindow` (max 60000ms). Identisches Muster zu MEXC (Plan 2b-2).
- `GET /api/v3/myTrades` - Trades für **ein konkretes Handelspaar**
  (`symbol` ist Pflichtparameter, wie bei MEXC). Zwei Abfragemodi:
  - `startTime`/`endTime`: Fenster darf **max. 24 Stunden** auseinander
    liegen.
  - `fromId`: liefert Trades ab einer Trade-ID aufwärts, **ohne**
    Zeitfenster-Beschränkung - damit ist die komplette Handelshistorie
    abrufbar (anders als MEXCs harte 30-Tage-Grenze). `fromId` kann
    nicht mit `startTime`/`endTime` kombiniert werden. Ohne beides
    werden die neuesten Trades geliefert.
  - `limit`: Default 500, Max 1000.
  - Felder: `id`, `orderId`, `symbol`, `price`, `qty`, `quoteQty`,
    `commission`, `commissionAsset`, `time`, `isBuyer`.
- `GET /sapi/v1/capital/deposit/hisrec` - Einzahlungen. Kein Symbol-
  Zwang, aber **max. 90 Tage** zwischen `startTime` und `endTime` pro
  Abfrage (Default-Zeitraum ohne Angabe: letzte 90 Tage). `limit` max
  1000. Felder: `id`, `amount`, `coin`, `network`, `status`, `txId`,
  `insertTime`. **Status `1` = erfolgreich gutgeschrieben** (andere
  Codes: 0=pending, 6=gutgeschrieben aber nicht auszahlbar, 7=fehlerhaft,
  8=wartet auf Bestätigung - werden übersprungen).
- `GET /sapi/v1/capital/withdraw/history` - Auszahlungen. Kein Symbol-
  Zwang, **max. 90 Tage** Fenster pro Abfrage (ohne `withdrawOrderId`;
  mit `withdrawOrderId` sogar nur 7 Tage - wird hier nicht verwendet).
  `limit` max 1000. Felder: `id`, `amount`, `transactionFee`, `coin`,
  `status`, `applyTime`, `txId`. **Status `6` = erfolgreich
  abgeschlossen** (andere Codes = verschiedene Zwischen-/Fehlerzustände
  - werden übersprungen).

Quellen: [Binance Open Platform - Account Endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints),
[Deposit History](https://developers.binance.com/docs/wallet/capital/deposite-history),
[Withdraw History](https://developers.binance.com/docs/wallet/capital/withdraw-history),
[binance-spot-api-docs rest-api.md](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md).

**Hinweis für die Umsetzung:** Binances API-Oberfläche kann sich ändern.
Vor der Implementierung kurz gegen die aktuelle Dokumentation prüfen.

## Wichtige Unterschiede zu MEXC (Plan 2b-2)

1. **Trades sind vollständig abrufbar, nicht auf 30 Tage begrenzt.**
   Statt (wie bei MEXC) bei jedem Sync nur ein festes Zeitfenster
   abzufragen, paginiert der Binance-Adapter pro konfiguriertem Paar
   per `fromId` (aufsteigend, 1000er-Seiten) durch die **komplette**
   Trade-Historie und verlässt sich - wie MEXC/Kraken - auf die
   bestehende `external_id`-Dedup-Prüfung in `sync.py`, um bereits
   gespeicherte Trades nicht doppelt zu verarbeiten. Das bedeutet: jeder
   Sync kostet so viele `myTrades`-Aufrufe wie `ceil(Anzahl_Trades /
   1000)` pro Paar - für ein persönliches Steuer-Tool mit gelegentlichem
   manuellem Sync unproblematisch (Rate-Limit-Gewicht 20 pro Aufruf ohne
   `orderId`, Konto-Limit i.d.R. mehrere Tausend Gewicht/Minute). Keine
   30-Tage-Dokumentations-Warnung nötig wie bei MEXC.
2. **Ein-/Auszahlungen brauchen 90-Tage-Fenster-Pagination.** Anders als
   MEXC (das beliebig lange Zeiträume in einer Abfrage mit `startTime`/
   `endTime` erlaubt und nur bei >1000 Datensätzen nachpaginiert) deckelt
   Binance jede Abfrage auf max. 90 Tage. Der Adapter iteriert deshalb in
   90-Tage-Schritten von `effective_since` (bzw. einem festen
   "Projektbeginn"-Fallback, wenn `since is None` - siehe unten) bis
   `jetzt`, und innerhalb jedes 90-Tage-Fensters zusätzlich mit
   `offset`/`limit` nach, falls >1000 Datensätze in einem Fenster liegen.
3. **Kein "Anfangsdatum" für die erste Vollsynchronisation bei
   Ein-/Auszahlungen.** Binance liefert ohne `startTime` nur die letzten
   90 Tage - es gibt keinen "gib mir alles"-Modus. Für den allerersten
   Sync (`since is None`) wird deshalb ein konfigurierbares
   `BINANCE_SYNC_START` (ISO-Datum, z.B. Konto-Erstellungsdatum) als
   Startpunkt der 90-Tage-Fenster-Schleife verwendet. Ist es nicht
   gesetzt, wird auf 5 Jahre vor "jetzt" zurückgefallen (großzügige
   Obergrenze, die die allermeisten Binance-Konten abdeckt - günstiger
   als stillschweigend Daten zu verpassen). Trades sind davon nicht
   betroffen, da `fromId`-Pagination immer bei Trade-ID 0 beginnt und
   somit automatisch die komplette Historie erfasst.
4. **Watermark-Fix von Anfang an mit eingebaut** (nicht wie bei
   Coinbase/MEXC erst im finalen Review gefunden): Ein-/Auszahlungen
   teilen sich einen Sync-Watermark; späte Statuswechsel
   (pending->erfolgreich) könnten sonst dauerhaft verpasst werden.
   Direkt mit `SYNC_LOOKBACK = timedelta(days=7)` umgesetzt, wie bei
   Coinbase/MEXC etabliert - `effective_since = since - SYNC_LOOKBACK`,
   sowohl für den Fenster-Start als auch als client-seitiger Filter.

## Normalisierung

- `source_type="exchange"`, `source_name="binance"`.
- **Trades** (`myTrades`, pro konfiguriertem Paar): jede Zeile ist
  bereits ein einzelner, abgeschlossener Fill. `tx_type="swap"`. Bei
  `isBuyer=true`: `asset=BASE`, `amount=qty`, `counter_asset=QUOTE`,
  `counter_amount=quoteQty`. Bei `isBuyer=false` (Verkauf):
  `asset=QUOTE`, `amount=quoteQty`, `counter_asset=BASE`,
  `counter_amount=qty` (identisches Muster zu MEXC/Kraken: "asset" =
  was man bekommen hat). `fee_amount=commission`,
  `fee_asset=commissionAsset`. `external_id =
  f"trade-{pair.symbol}-{record['id']}"` (Trade-IDs sind pro Symbol
  vergeben).
- **Einzahlungen** (`deposit/hisrec`): nur `status == 1` wird
  übernommen. `tx_type="transfer_in"`, `asset=coin`, `amount=amount`.
  `external_id = f"deposit-{id}"` (Binance liefert stabile `id`-Felder
  pro Deposit-Datensatz, zuverlässiger als `txId`, das bei internen
  Transfers leer sein kann).
- **Auszahlungen** (`withdraw/history`): nur `status == 6` wird
  übernommen. `tx_type="transfer_out"`, `asset=coin`, `amount=amount`,
  `fee_amount=transactionFee`, `fee_asset=coin` (Netzwerkgebühren bei
  Krypto-Auszahlungen werden im selben Asset bezahlt). `external_id =
  f"withdrawal-{id}"`.
- Kein CHF-Preis-Feld aus Binance übernommen - wie bei allen anderen
  Quellen übernimmt die bestehende CoinGecko-Preisanreicherung in
  `sync.py` die CHF-Bewertung.

## Konfiguration

Analog zu MEXC:

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
BINANCE_TRADING_PAIRS=BTCUSDT:BTC:USDT,ETHUSDT:ETH:USDT
BINANCE_SYNC_START=2020-01-01   # optional, Fallback: 5 Jahre vor "jetzt"
```

`parse_trading_pairs()` aus `app/config.py` (bereits vorhanden, exakt
gleiches `SYMBOL:BASE:QUOTE`-Format wie MEXC) wird wiederverwendet -
keine neue Parsing-Funktion nötig. Eine neue kleine Funktion
`parse_sync_start(env_value: str | None) -> datetime | None` wird für
`BINANCE_SYNC_START` ergänzt (ISO-Datum -> UTC-`datetime`, `None` bei
leer/fehlend).

## Pagination & Sync

- `deposit/hisrec` / `withdraw/history`: äußere Schleife über 90-Tage-
  Fenster von `effective_since` (bzw. `BINANCE_SYNC_START`-Fallback bei
  `since is None`) bis `jetzt`; innerhalb jedes Fensters `offset`-
  basierte Nachpagination in 1000er-Schritten, analog zum bestehenden
  Pagination-Muster der anderen Adapter.
- `myTrades`: innere Schleife über `fromId` (Start bei `0`, dann jeweils
  `letzte_id_der_seite + 1`), 1000er-Seiten, bis eine Seite `<1000`
  Datensätze liefert. Kein `since`-Bezug nötig - läuft bei jedem Sync
  immer komplett durch, Dedup übernimmt `sync.py`.
- 429-Retry mit Backoff (`MAX_RETRIES=3`, `time.sleep(2**attempt)`) wie
  bei Coinbase/MEXC etabliert, in der gemeinsamen `_get()`-Hilfsmethode.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  API-Calls.
- HMAC-Signierung isoliert getestet (analog zu Kraken-/MEXC-
  Signierungstests).
- Trade-Normalisierung (Buy/Sell-Richtung via `isBuyer`), `fromId`-
  Pagination über mehrere Seiten, Deposit-/Withdrawal-Status-Filter,
  90-Tage-Fenster-Pagination (inkl. Fall: Zeitraum > 90 Tage seit letztem
  Sync erzeugt mehrere Fenster-Abfragen), Multi-Paar-Iteration,
  Watermark-Lookback (später abgeschlossene Ein-/Auszahlung wird beim
  nächsten Sync trotz bereits fortgeschrittenem Watermark erfasst).

## Offene Punkte für die Umsetzungsplanung

Keine - Design orientiert sich eng am bereits bestätigten MEXC-Muster
(Plan 2b-2); die Abweichungen (fromId-Pagination ohne Zeit-Deckel bei
Trades, 90-Tage-Fenster bei Ein-/Auszahlungen, `BINANCE_SYNC_START`-
Fallback) sind durch die Binance-API-Dokumentation vorgegeben, nicht
durch offene Design-Entscheidungen.
