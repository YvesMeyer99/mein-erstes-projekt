# Phase 4c – Cardano-Adapter – Design

Datum: 2026-08-08

## Zweck

Cardano als neue Chain hinzufügen: native ADA- und Cardano-Native-Token-
Transfers (CNTs, Cardanos Äquivalent zu ERC-20/SPL) erfassen. Wie bei
Bitcoin unterstützen Cardano-Wallets HD-Adressableitung
(CIP-1852) - eine einzelne fest eingetragene Adresse kann daher
Transaktionen verpassen, wenn die Wallet (z.B. AtomicWallet) neue
Adressen pro Empfang generiert.

## API-Recherche (Stand: 2026-08-08, via Koios-Community-API)

- **Basis-URL:** `https://api.koios.rest/api/v1` - kostenloser,
  öffentlicher Cardano-Query-Layer, **kein API-Key nötig**. Rate-Limit:
  100 Anfragen/10s pro IP (großzügig für gelegentlichen manuellen Sync).
- **`GET /account_txs`** (`_stake_address`, optional
  `_after_block_height`) - liefert alle Transaktions-Hashes für eine
  **Stake-Adresse** (`stake1...`), inkl. `block_time`. **Zentraler
  Vorteil gegenüber Bitcoins xpub-Ansatz:** Koios aggregiert serverseitig
  bereits alle Zahlungsadressen, die zu dieser Stake-Adresse gehören -
  **keine eigene HD-Ableitung/Gap-Limit-Scanning nötig**, einfach die
  Stake-Adresse übergeben.
- **`POST /account_addresses`** (`_stake_addresses`-Array) - liefert
  alle Zahlungsadressen, die zu einer Stake-Adresse gehören. Wird
  benötigt, um die "owned addresses"-Menge für die korrekte
  Netto-Berechnung zu kennen (s.u.) - nicht für die
  Transaktions-Discovery selbst (die übernimmt `/account_txs` bereits).
- **`POST /address_txs`** (Adress-Array, optional
  `_after_block_height`) - liefert Transaktions-Hashes für einzelne,
  fest angegebene Zahlungsadressen (analog zu `BITCOIN_ADDRESSES`).
- **`POST /tx_info`** (`_tx_hashes`-Array) - liefert Transaktionsdetails:
  `fee` (Lovelace), `inputs`/`outputs` je mit Zahlungsadresse, Wert in
  Lovelace, und `asset_list` (native Tokens: `policy_id`, `asset_name`,
  `quantity`) pro UTXO.

Quellen: [Koios API-Doku](https://api.koios.rest/),
[Koios OpenAPI-Spec](https://github.com/cardano-community/koios-artifacts).

**Hinweis für die Umsetzung:** Die exakten Feldnamen/Verschachtelung von
`/tx_info`s Antwort (insbesondere ob `payment_addr` als String oder
verschachteltes Objekt `{bech32: "..."}` vorliegt) konnten während der
Recherche nicht abschließend verifiziert werden - vor der
Implementierung kurz gegen die aktuelle API-Antwort prüfen (z.B. echter
Testaufruf mit einer öffentlich bekannten Adresse). Die *Absicht*
(UTXO-Modell, Netto-Berechnung wie bei Bitcoin) ist maßgeblich, nicht
die exakte Feldbezeichnung - derselbe Recherche-Vorbehalt, der sich bei
`bitcoinlib` in Phase 4a bereits bewährt hat.

## Konfiguration (mit Nutzer bestätigt: beide Wege unterstützen)

```
CARDANO_ADDRESSES=main:addr1einzelneAdresse...
CARDANO_STAKE_ADDRESSES=atomic:stake1meineStakeAdresse...
```

Beide Formate identisch zu `BITCOIN_ADDRESSES`/`BITCOIN_XPUBS` -
`parse_wallets()` wird unverändert wiederverwendet. `CARDANO_ADDRESSES`
für einzelne, bekannte feste Adressen (z.B. eine Exchange-Adresse),
`CARDANO_STAKE_ADDRESSES` für ganze Wallets (empfohlen, löst das
Adressrotations-Problem ohne eigene HD-Ableitung).

## Architektur

Zwei Adapter, die dieselbe Netto-Berechnungslogik teilen (Muster von
Bitcoin/`BitcoinXpubAdapter` übernommen - `owned_addresses: set[str]`
statt einzelner Adresse, damit interne Verschiebungen zwischen eigenen
Adressen korrekt zu Null saldiert werden):

- **`CardanoAdapter`** (einzelne Adresse): `owned_addresses = {address}`,
  Transaktions-Discovery über `/address_txs`.
- **`CardanoStakeAdapter`** (Stake-Adresse): `owned_addresses` wird
  einmalig über `/account_addresses` aufgelöst, Transaktions-Discovery
  direkt über `/account_txs` (kein Gap-Limit-Scanning nötig - Koios
  liefert die vollständige Liste server-seitig).

Beide nutzen dieselbe gemeinsame Normalisierungsfunktion
(`normalize_cardano_tx(tx, owned_addresses, account_label, since)`),
analog zu `app.adapters.bitcoin.normalize_bitcoin_tx`.

**Wichtige Lehre aus Phase 4a übernommen:** die "vollständig interne
Transaktion" (alle Inputs UND alle Outputs gehören zu `owned_addresses`)
wird **von Anfang an** explizit erkannt und übersprungen (nicht erst
nachträglich per TDD-Fix wie beim Bitcoin-xpub-Adapter) - sonst würde
eine interne Wallet-Verschiebung mit Netzwerkgebühr fälschlich als
Mini-Transaktion erscheinen.

## Normalisierung

- `source_type="chain"`, `source_name="cardano"` (für beide Adapter -
  fachlich dieselbe Chain, Unterscheidung über `account_label`).
- **ADA:** Netto-Lovelace = Summe(Outputs an `owned_addresses`) -
  Summe(Inputs von `owned_addresses`). `tx_type` nach Vorzeichen,
  `net_lovelace == 0` → übersprungen. `fee_amount`/`fee_asset="ADA"` nur
  wenn `net_lovelace < 0` (wir sind die ausgehende Seite) - die Gebühr
  ist bereits Teil des Netto-Abflusses (wie bei Bitcoin/Solana), wird
  nur zusätzlich separat ausgewiesen.
- **Native Tokens (CNTs):** pro `(policy_id, asset_name)`-Kombination
  mit Netto-Änderung `!= 0` ein eigener Eintrag. `asset` =
  `f"{policy_id}{asset_name}"` (roher Hex-String, kein Symbol-Mapping -
  analog zur bereits akzeptierten ERC-20/SPL-Einschränkung).
  **Menge wird als rohe Ganzzahl ohne Dezimalstellen-Anpassung
  gemeldet** - anders als bei SPL-Tokens gibt es auf Cardano-Protokoll-
  Ebene kein verbindliches `decimals`-Feld (Dezimalstellen sind nur
  Konvention einer externen Metadaten-Registry, deren Einbindung
  zusätzliche Komplexität/Abhängigkeit bedeuten würde - YAGNI für den
  aktuellen Scope, analog zur SPL-Entscheidung).
- **Mehrere normalisierte Einträge pro Transaktion möglich** (ADA-Bein +
  ein oder mehrere Token-Beine), `external_id` daher pro Bein eindeutig:
  `f"{tx_hash}-ADA"` bzw. `f"{tx_hash}-{policy_id}{asset_name}"` - sonst
  würde `sync.py`s Dedup-Prüfung ein zweites Bein derselben Transaktion
  fälschlich als bereits gespeichert überspringen (identisches Problem
  wie bei Solana bereits gelöst).
- Kein CHF-Preis-Feld aus Cardano übernommen - `COINGECKO_ID_MAP` wird
  um `"ADA": "cardano"` ergänzt, native Tokens bleiben unbewertet.

## Bekannte Einschränkungen

- **Native Tokens ohne Symbol/CHF-Kurs/Dezimalstellen** (siehe oben) -
  analog zur bestehenden ERC-20/SPL-Einschränkung, für die
  Steuererklärung muss der Nutzer Policy-ID/Asset-Name einmalig manuell
  einem bekannten Token zuordnen (z.B. über einen Cardano-Explorer wie
  cardanoscan.io).
- **Stake-Adresse ist datenschutzrelevant** (analog zum
  xpub-Datenschutzhinweis bei Bitcoin): macht die gesamte
  Adress-/Transaktionshistorie des Wallets einsehbar für jeden, der sie
  kennt - trotzdem vertraulich behandeln.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  Koios-Calls.
- ADA Transfer-In/-Out inkl. Gebühren-Zuordnung.
- Native-Token-Transfer, inkl. Fall "ADA- und Token-Bein in derselben
  Transaktion" (mehrere Einträge, unterschiedliche `external_id`s).
- **Vollständig interne Transaktion mit Gebühr wird korrekt
  übersprungen** (von Anfang an getestet, nicht erst nachträglich).
- `since`-Filterung.
- Pagination (`/account_txs`/`/address_txs` liefern laut Koios-Doku
  bis zu 1000 Zeilen pro Seite, mit `limit`/`offset` - Nachpagination
  wie bei den bestehenden Adaptern).
- `CardanoStakeAdapter`: Auflösung der Zahlungsadressen über
  `/account_addresses`, dann korrekte Netto-Berechnung über die volle
  Menge.

## Offene Punkte für die Umsetzungsplanung

Keine wesentlichen - die exakte Feldstruktur von `/tx_info` muss beim
Implementieren kurz gegen die aktuelle API-Antwort verifiziert werden
(siehe Hinweis oben), das ist ein Implementierungsdetail, keine offene
Design-Entscheidung.
