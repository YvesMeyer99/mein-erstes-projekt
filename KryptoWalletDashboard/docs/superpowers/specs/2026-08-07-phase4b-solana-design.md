# Phase 4b – Solana-Adapter – Design

Datum: 2026-08-07

## Zweck

Solana als neue Chain hinzufügen: native SOL- und SPL-Token-Transfers
(Solanas Äquivalent zu ERC-20) für eine oder mehrere konfigurierte
Adressen erfassen - z.B. mehrere Accounts desselben Ledger-Geräts.

## API-Recherche (Stand: 2026-08-07, via solana.com/docs/rpc)

- **Kein Adressformat-Problem wie bei Bitcoin:** Solana-Wallets
  (inklusive Ledger) verwenden im Normalfall eine feste Adresse pro
  Account, kein HD-Adress-Wechsel pro Transaktion. Mehrere Accounts =
  mehrere feste, eigenständige Adressen - **kein Gap-Limit-Scanning
  nötig**, einfache Adressliste reicht (wie bei `ETHEREUM_ADDRESSES`).
- **Basis-URL:** `https://api.mainnet-beta.solana.com` (öffentlicher
  Solana-RPC-Endpunkt, kein API-Key nötig, aber rate-limitiert - siehe
  unten). JSON-RPC-Protokoll (POST mit JSON-Body), nicht REST wie
  Blockstream/Etherscan - neues Muster für dieses Projekt.
- **`getSignaturesForAddress(address, {limit, before})`** - liefert
  Transaktions-Signaturen (neueste zuerst), inkl. `blockTime`
  (Unix-Timestamp, kann `null` sein) und `err` (Fehler-Objekt oder
  `null` bei Erfolg). Pagination: `before=<letzte Signatur der
  vorherigen Seite>`, endet wenn eine Seite `< limit` (max. 1000)
  Einträge liefert.
- **`getTransaction(signature, {encoding: "json",
  maxSupportedTransactionVersion: 0})`** - liefert Balance-Änderungen
  direkt, ohne Instruktionen selbst parsen zu müssen:
  - `meta.preBalances`/`meta.postBalances` - Lamports (1 SOL = 10⁹
    Lamports) vor/nach der Transaktion, indiziert nach
    `transaction.message.accountKeys`.
  - `meta.fee` - Netzwerkgebühr in Lamports, bezahlt vom Fee-Payer
    (erster Signer in `accountKeys`).
  - `meta.preTokenBalances`/`meta.postTokenBalances` - SPL-Token-
    Salden, je Eintrag `accountIndex`, `mint` (Token-Adresse), `owner`
    (Wallet-Adresse des Halters), `uiTokenAmount.amount` (Rohbetrag als
    String) + `uiTokenAmount.decimals`.
  - `meta.err` - Fehler-Objekt oder `null` (bereits auf
    Signatur-Ebene verfügbar, spart in der Regel einen Aufruf).

Quelle: [Solana RPC HTTP Methods](https://solana.com/docs/rpc/http/gettransaction),
[getSignaturesForAddress](https://solana.com/docs/rpc/http/getsignaturesforaddress).

**Hinweis für die Umsetzung:** Solanas RPC-API kann sich ändern - vor
der Implementierung kurz gegen die aktuelle Dokumentation prüfen.

## Normalisierung

- `source_type="chain"`, `source_name="solana"`.
- **Native SOL:** Nettobetrag = `postBalances[i] - preBalances[i]` für
  den Index `i` unserer Adresse in `accountKeys`. `net_lamports == 0`
  → keine SOL-Bewegung, dieses "Bein" wird übersprungen (analog zum
  Bitcoin-Muster). `tx_type="transfer_in"`/`"transfer_out"` je nach
  Vorzeichen. Ist unsere Adresse der Fee-Payer (erster Eintrag in
  `accountKeys`) UND `net_lamports < 0`, wird `fee_amount`/`fee_asset`
  aus `meta.fee` gesetzt (die Gebühr ist bereits Teil des
  Netto-Abflusses, wie bei Bitcoin - kein doppeltes Abziehen).
- **SPL-Tokens:** pro `mint` mit Netto-Änderung `!= 0` für unsere
  Adresse (per `owner`-Feld in `preTokenBalances`/`postTokenBalances`
  identifiziert, über `accountIndex` gematcht) ein eigener Eintrag.
  `asset` = der **rohe Mint-Adresse-String** (kein Symbol-Mapping wie
  `USDC`/`USDT`) - siehe Einschränkung unten.
- **Ein Signatur kann mehrere normalisierte Einträge erzeugen** (z.B.
  ein SOL-Bein + ein Token-Bein bei einem DEX-Swap). Kein
  Swap-Pairing wie bei Kraken/MEXC - jede Asset-Bewegung wird
  eigenständig als `transfer_in`/`transfer_out` gemeldet (ehrlicher als
  eine unsichere Heuristik "das war ein Swap" zu raten; entspricht dem
  bestehenden Chain-Adapter-Muster von Bitcoin/EVM, die ebenfalls keine
  Swap-Erkennung machen). `external_id` wird daher pro Bein eindeutig
  gemacht: `f"{signature}-native"` für die SOL-Bewegung,
  `f"{signature}-{mint}"` pro Token-Bewegung - sonst würde
  `sync.py`s Dedup-Prüfung (Schlüssel `external_id`) das zweite Bein
  derselben Signatur fälschlich als bereits gespeichert überspringen.
- Fehlgeschlagene Transaktionen (`err != null`, bereits auf
  Signatur-Ebene erkennbar) werden übersprungen, ohne dass überhaupt
  `getTransaction` dafür aufgerufen wird (spart API-Calls).
- Kein CHF-Preis-Feld aus Solana übernommen - wie bei allen anderen
  Quellen übernimmt die bestehende CoinGecko-Preisanreicherung in
  `sync.py` die CHF-Bewertung für `SOL` (native Asset, ergänzt in
  `COINGECKO_ID_MAP`).

## Bekannte Einschränkung: SPL-Tokens ohne Symbol/CHF-Kurs

Anders als bei EVM/Etherscan (das ERC-20-Token-Symbole direkt in der
API-Antwort liefert) gibt Solanas `getTransaction`-Antwort **kein
Token-Symbol** zurück, nur die Mint-Adresse. Ein vollständiges
Symbol-Mapping würde eine zusätzliche Datenquelle (z.B. eine
Token-Liste wie Jupiters oder Metaplex-On-Chain-Metadaten) erfordern -
zusätzliche Komplexität/Abhängigkeit, die für den aktuellen Scope nicht
gerechtfertigt ist (YAGNI, analog zur bereits akzeptierten
ERC-20-Einschränkung "keine CHF-Bewertung"). SPL-Token-Transaktionen
werden also vollständig erfasst (Menge, Zeitpunkt, Richtung), erscheinen
im CSV-Export aber mit der rohen Mint-Adresse als "Asset" statt einem
lesbaren Namen wie "USDC", und ohne CHF-Kurs. Für die Steuererklärung
muss der Nutzer die Mint-Adresse einmalig manuell einem bekannten Token
zuordnen (z.B. über einen Solana-Explorer).

## Pagination & Sync

- `getSignaturesForAddress`: 1000er-Seiten via `before`-Cursor, endet
  bei einer Seite `< 1000` Einträgen.
- **Effizienz-Optimierung:** `blockTime` und `err` sind bereits auf
  Signatur-Ebene verfügbar - Filterung nach `since` und nach
  fehlgeschlagenen Transaktionen passiert **vor** dem teureren
  `getTransaction`-Aufruf, nicht danach.
- Kein RPC-Retry/Backoff bei Rate-Limits geplant für die erste Version
  (öffentlicher Endpunkt, gelegentlicher manueller Sync - analog zur
  bereits akzeptierten Entscheidung bei Bitcoin, keine Retry-Logik für
  Blockstream einzubauen). Bei wiederholten Rate-Limit-Problemen in der
  Praxis kann das in einem späteren, kleinen Plan nachgerüstet werden.

## Konfiguration

```
SOLANA_ADDRESSES=ledger-1:AdresseAlsBase58...,ledger-2:AdresseAlsBase58...
```

Format identisch zu `ETHEREUM_ADDRESSES`/`BITCOIN_ADDRESSES` -
`parse_wallets()` wird unverändert wiederverwendet, keine neue
Parsing-Funktion nötig. RPC-Endpunkt ist fest codiert (mit Nutzer
bestätigt), keine Konfigurationsoption.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  RPC-Calls.
- Native SOL Transfer-In/-Out inkl. Gebühren-Zuordnung (nur wenn
  Fee-Payer).
- SPL-Token-Transfer, inkl. Fall "SOL- und Token-Bein in derselben
  Signatur" (zwei Einträge, unterschiedliche `external_id`s).
- Fehlgeschlagene Transaktionen werden übersprungen, ohne
  `getTransaction`-Aufruf.
- `since`-Filterung auf Signatur-Ebene (vor `getTransaction`).
- Pagination über `getSignaturesForAddress`.
- Mehrere konfigurierte Adressen werden unabhängig verarbeitet.

## Offene Punkte für die Umsetzungsplanung

Keine - Design wurde durchgesprochen und mit dem Nutzer bestätigt
(SPL-Tokens ja, RPC-Endpunkt fest codiert). Die SPL-Symbol-Auflösung
und ein konfigurierbarer RPC-Endpunkt bleiben bewusst außerhalb des
Scopes (siehe oben) und könnten bei Bedarf spätere, eigene Pläne sein.
