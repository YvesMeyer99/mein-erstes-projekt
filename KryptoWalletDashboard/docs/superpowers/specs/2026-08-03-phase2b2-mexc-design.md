# Plan 2b-2 – MEXC-Adapter – Design

Datum: 2026-08-03

## Zweck

Zweite Börsen-Erweiterung von Plan 2b: ein Adapter für MEXC, der
Ein-/Auszahlungen automatisch sowie Trades für manuell konfigurierte
Handelspaare erfasst. Baut auf dem bereits abgeschlossenen Phase-1-
Backend, Plan 2a (EVM-Chains) und Plan 2b-1 (Coinbase) auf.

## API-Recherche (Stand: 2026-08-03, via MEXC Spot API v3 Docs)

- Basis-URL: `https://api.mexc.com`
- Auth: `X-MEXC-APIKEY`-Header + `signature`-Query-Parameter =
  `HMAC-SHA256(alle Query-Parameter als String, secretKey)`, lowercase
  Hex. Pflicht-Parameter jeder privaten Anfrage: `timestamp` (ms),
  optional `recvWindow` (Default 5000ms, max 60000ms).
- `GET /api/v3/myTrades` – Trades für **ein konkretes Handelspaar**
  (`symbol`, z.B. `BTCUSDT`, ist **Pflichtparameter** – es gibt keinen
  "alle Trades"-Endpunkt). **Nur die letzten 30 Tage** sind abrufbar
  ("Only the transaction records in the past 1 month can be queried" –
  laut Doku explizit, unabhängig von `startTime`/`endTime`). Felder:
  `id`, `orderId`, `symbol`, `price`, `qty`, `quoteQty`, `commission`,
  `commissionAsset`, `time`, `isBuyer`.
- `GET /api/v3/capital/deposit/hisrec` – Einzahlungen, kein Symbol-Zwang.
  Felder: `amount`, `coin`, `network`, `status` (Codes 1-12; **5=SUCCESS,
  12=COMPLETED** gelten als abgeschlossen), `txId`, `insertTime`.
- `GET /api/v3/capital/withdraw/history` – Auszahlungen, kein Symbol-
  Zwang. Felder: `amount`, `coin`, `transactionFee`, `status` (Codes
  1-10; **7=SUCCESS**), `txId`, `applyTime`, `id`.

Quellen: [MEXC Spot API v3 Docs](https://mexcdevelop.github.io/apidocs/spot_v3_en/).

**Hinweis für die Umsetzung:** MEXCs API-Oberfläche kann sich ändern.
Vor der Implementierung kurz gegen die aktuelle Dokumentation prüfen.

## Wichtige Einschränkung: Trades nur für konfigurierte Paare, nur 30 Tage

Anders als Kraken (ein generischer Ledger-Endpunkt) oder Coinbase
(automatische Konten-Erkennung) verlangt MEXC pro Trade-Abfrage ein
konkretes Handelspaar, und liefert grundsätzlich nur die letzten 30
Tage. Entschieden (mit Nutzer bestätigt):

- **Handelspaare werden manuell konfiguriert** (`MEXC_TRADING_PAIRS`),
  analog zu den bestehenden `BITCOIN_ADDRESSES`/`ETHEREUM_ADDRESSES`-
  Config-Mustern. Format: `SYMBOL:BASE:QUOTE` kommagetrennt, z.B.
  `BTCUSDT:BTC:USDT,ETHUSDT:ETH:USDT` – Base/Quote werden explizit
  mitgegeben statt aus dem Symbol geraten zu werden (MEXC-Symbole sind
  Base+Quote ohne Trennzeichen aneinandergehängt, z.B. `BTCUSDT` könnte
  ohne bekannte Quote-Liste nicht zuverlässig in `BTC`+`USDT` zerlegt
  werden).
- **Ein-/Auszahlungen laufen automatisch**, kein Paar-Zwang.
- **Harte Dokumentations-Pflicht:** die 30-Tage-Grenze und die Notwendigkeit
  regelmäßiger Syncs (mind. monatlich) werden explizit im README
  dokumentiert, analog zur bereits bestehenden CoinGecko-Free-Tier-
  Einschränkung. Ältere Trade-Historie muss der Nutzer einmalig per
  CSV-Export von der MEXC-Webseite (unterstützt bis zu 3 Jahre) manuell
  nachtragen – das ist außerhalb des Scopes dieses Adapters.

## Normalisierung

- `source_type="exchange"`, `source_name="mexc"`.
- **Trades** (`myTrades`, pro konfiguriertem Paar): jede Zeile ist
  bereits ein einzelner, abgeschlossener Fill (kein Pairing wie bei
  Kraken nötig). `tx_type="swap"`. Bei `isBuyer=true`: `asset=BASE`,
  `amount=qty`, `counter_asset=QUOTE`, `counter_amount=quoteQty`. Bei
  `isBuyer=false` (Verkauf): `asset=QUOTE`, `amount=quoteQty`,
  `counter_asset=BASE`, `counter_amount=qty` (das erhaltene Quote-Asset
  wird zum "asset", das abgegebene Base-Asset zum "counter_asset" –
  gleiches Muster wie bei Kraken: "asset" = was man bekommen hat).
  `fee_amount=commission`, `fee_asset=commissionAsset`.
  `external_id = "trade-" + id` (Trade-IDs sind pro Symbol vergeben,
  daher wird das Symbol zur Sicherheit mit in die ID eingebaut:
  `f"trade-{symbol}-{id}"`).
- **Einzahlungen** (`deposit/hisrec`): nur `status in {5, 12}` wird
  übernommen. `tx_type="transfer_in"`, `asset=coin`, `amount=amount`.
  `external_id = f"deposit-{txId}"` (falls `txId` leer/fehlt, Fallback
  auf eine von MEXC gelieferte Datensatz-ID, falls vorhanden – sonst
  wird der Datensatz übersprungen, da keine stabile ID zur Dedup-Prüfung
  vorhanden wäre).
- **Auszahlungen** (`withdraw/history`): nur `status == 7` wird
  übernommen. `tx_type="transfer_out"`, `asset=coin`, `amount=amount`,
  `fee_amount=transactionFee`, `fee_asset=coin` (Netzwerkgebühren bei
  Krypto-Auszahlungen werden im selben Asset bezahlt). `external_id =
  f"withdrawal-{id}"`.
- Kein CHF-Preis-Feld aus MEXC übernommen – wie bei allen anderen
  Quellen übernimmt die bestehende CoinGecko-Preisanreicherung in
  `sync.py` die CHF-Bewertung.

## Pagination & Sync

- `deposit/hisrec`/`withdraw/history`: `startTime`/`endTime`/`limit`
  (max 1000) – falls mehr als 1000 Datensätze im Zeitraum liegen, wird
  in 1000er-Schritten mit angepasstem `startTime` nachpaginiert, analog
  zum bestehenden Pagination-Muster der anderen Adapter.
- `myTrades`: kein `since`-Nutzen über die eigene 30-Tage-Grenze hinaus
  möglich; der Adapter fragt bei jedem Sync einfach die maximal
  verfügbaren letzten 30 Tage ab und verlässt sich auf die bestehende
  `external_id`-Dedup-Prüfung in `sync.py`, um bereits gespeicherte
  Trades nicht doppelt zu verarbeiten.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  API-Calls.
- HMAC-Signierung wird isoliert getestet (analog zum bestehenden Kraken-
  Signierungstest aus Phase 1).
- Trade-Normalisierung (Buy/Sell-Richtung via `isBuyer`), Deposit-/
  Withdrawal-Status-Filter, Pagination, Multi-Paar-Iteration.

## Offene Punkte für die Umsetzungsplanung

Keine – Design wurde durchgesprochen und bestätigt. Binance bleibt ein
eigener, späterer Plan.
