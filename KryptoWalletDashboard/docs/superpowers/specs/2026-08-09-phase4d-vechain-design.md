# Phase 4d – VeChain-Adapter – Design

Datum: 2026-08-09

## Zweck

VeChain (VeChainThor) als neue Chain hinzufügen: native VET- und
VIP-180-Token-Transfers (VeChains ERC-20-Äquivalent, inkl. expliziter
VTHO-Transfers) erfassen.

## API-Recherche (Stand: 2026-08-09, via offizieller Thorest-API)

- **Basis-URL:** `https://sync-mainnet.vechain.org` (öffentlicher,
  offizieller VeChain-Node, **kein API-Key nötig**). Alternative
  Community-Knoten existieren (z.B. veblocks.net), aber der offizielle
  Node reicht für gelegentlichen manuellen Sync.
- **Adressformat identisch zu Ethereum** (`0x` + 40 Hex-Zeichen,
  secp256k1-Adressableitung wie bei EVM-Chains) - **keine
  Adressrotation** wie bei Bitcoin/Cardano, eine einfache Adressliste
  reicht (analog zu `ETHEREUM_ADDRESSES`/`SOLANA_ADDRESSES`).
- **`POST /logs/transfer`** - liefert native VET-Transfers direkt als
  diskrete Bewegungen (kein UTXO-Modell wie bei Bitcoin/Cardano, kein
  Adresslisten-Netting nötig): `sender`, `recipient`, `amount` (Hex-Wei-
  String), `meta.{blockTimestamp, txID, clauseIndex, ...}`. Filterbar
  über `criteriaSet` (mehrere Kriterien werden ODER-verknüpft) nach
  `sender`/`recipient` - eine Abfrage mit `[{sender: adresse},
  {recipient: adresse}]` liefert alle Transfers, an denen die Adresse
  beteiligt ist.
- **`POST /logs/event`** - liefert generische Contract-Events, u.a.
  VIP-180-Token-Transfers (identisches Event-Signatur-Schema wie
  ERC-20: `Transfer(address,address,uint256)`, Topic0 =
  `0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`).
  Filterbar nach `address` (Contract) und bis zu 4 indizierten `topics`.
  Adressen in `topic1`/`topic2` sind auf 32 Bytes gepolstert (die
  eigentliche Adresse sind die letzten 20 Bytes/40 Hex-Zeichen).
- **VTHO (Gas-Token) ist selbst ein VIP-180-Vertrag** an der fest
  bekannten Adresse `0x0000000000000000000000000000456E65726779` -
  **keine Sonderbehandlung nötig**, explizite VTHO-Transfers werden
  über denselben generischen VIP-180-Mechanismus erfasst wie jeder
  andere Token.

Quellen: [Thorest-API-Doku](https://sync-mainnet.vechain.org/doc/thor.yaml),
[VeChain Docs - Dual-Token-Modell](https://docs.vechain.org/introduction-to-vechain/dual-token-economic-model),
[VeChain Docs - Built-in Contracts](https://docs.vechain.org/developer-resources/built-in-contracts).

**Hinweis für die Umsetzung:** mehrere Details der Thorest-API-Struktur
(exakte Feldnamen von `FilterRange`/`FilterOptions`/Pagination, ob
`criteriaSet` tatsächlich ODER-verknüpft, exaktes `meta`-Objekt-Schema)
konnten während der Recherche nicht abschließend verifiziert werden -
**wie bei der Cardano-Phase** (wo Live-API-Verifikation drei echte,
sonst unbemerkte Fehler aufdeckte) muss vor der Implementierung ein
echter, unauthentifizierter Testaufruf gegen die Live-API erfolgen. Die
*Absicht* ist maßgeblich, nicht die exakte Skizze unten.

## Wichtige Design-Entscheidung: keine Gebühren-Verflechtung

Anders als bei Bitcoin/Solana/Cardano wird die Netzwerkgebühr bei
VeChain in einem **komplett anderen Asset** (VTHO) bezahlt als der
transferierte Wert (VET) - die Gebühr wird also nie vom VET-Betrag
abgezogen, `amount` bei einem VET-Transfer ist immer exakt der
gesendete/empfangene Betrag, keine Netto-Berechnung wie bei UTXO-Chains
nötig.

**Bewusst außerhalb des Scopes:** VTHO, das als reine Netzwerkgebühr
verbraucht wird (nicht explizit transferiert, sondern beim
Transaktions-Versand protokollintern verbraucht), wird **nicht**
erfasst - das würde einen zusätzlichen API-Aufruf pro Transaktion
(Transaktions-Beleg/Receipt abrufen) erfordern, für den Scope dieses
Adapters nicht gerechtfertigt (YAGNI, analog zu bereits akzeptierten
Scope-Grenzen). Explizite VTHO-*Transfers* (jemand sendet dir VTHO,
oder du sendest VTHO) werden dagegen wie jeder andere VIP-180-Token
erfasst.

## Normalisierung

- `source_type="chain"`, `source_name="vechain"`.
- **VET:** pro `/logs/transfer`-Eintrag mit `sender`/`recipient` !=
  (Selbst-Transfer wird übersprungen, kein Netto-Effekt) und
  `amount != 0`: `tx_type="transfer_in"` wenn `recipient` unsere
  Adresse ist, `"transfer_out"` wenn `sender` unsere Adresse ist.
  `amount = int(amount_hex, 16) / 10**18`. Kein `fee_amount` (siehe
  oben - Gebühr ist ein komplett separates Asset, wird nicht erfasst).
- **VIP-180-Tokens (inkl. VTHO):** pro `/logs/event`-Eintrag mit
  `topic0` = Transfer-Signatur, dekodierter `sender`/`recipient` aus
  `topic1`/`topic2`, `amount = int(data, 16)`. **Vereinfachende
  Annahme: 18 Dezimalstellen für alle VIP-180-Tokens** (wie VET/VTHO
  und die überwiegende Mehrheit der VeChain-Ökosystem-Tokens) - anders
  als bei Cardano (wo mangels verlässlicher Konvention der rohe
  Ganzzahlwert gezeigt wird) ist eine feste Dezimalstellen-Annahme hier
  vertretbar, da 18 Dezimalstellen der EVM-Standard-Konvention
  entspricht, die praktisch alle VIP-180-Tokens übernehmen. **Bekannte
  Einschränkung:** ein seltener Token mit abweichender Dezimalstellen-
  Zahl (z.B. 6 wie manche Stablecoins auf anderen Chains) würde falsch
  skaliert angezeigt - für die Steuererklärung im Zweifel gegen einen
  VeChain-Explorer (z.B. vechainstats.com) verifizieren.
  `asset` = die Contract-Adresse (roher Bezeichner, kein Symbol-Mapping
  - analog zu ERC-20/SPL/CNT).
- **Mehrere Einträge pro Transaktion möglich** (VeChain-Transaktionen
  können mehrere "Clauses" mit je mehreren Transfers enthalten) -
  `external_id` daher eindeutig pro Eintrag:
  `f"{txID}-{clauseIndex}-VET-{laufender_index}"` bzw.
  `f"{txID}-{clauseIndex}-{contract_adresse}-{laufender_index}"`.
- Kein Swap-Pairing (analog zu Bitcoin/Solana/Cardano) - jede
  Asset-Bewegung wird eigenständig als `transfer_in`/`transfer_out`
  gemeldet.
- Kein CHF-Preis-Feld aus VeChain übernommen - `COINGECKO_ID_MAP` wird
  um `"VET": "vechain"` und `"VTHO": "vethor-token"` ergänzt, sonstige
  VIP-180-Tokens bleiben unbewertet.

## Sync-Verhalten

- Analog zum bereits etablierten "immer neu abfragen, auf `sync.py`s
  Dedup verlassen"-Muster (Binance-Trades, MEXC): kein server-seitiges
  `since`-Filtern über unsichere API-Details, stattdessen client-seitige
  Filterung nach `meta.blockTimestamp` auf dem vollständigen
  Abfrage-Ergebnis. Pagination über `FilterOptions` (exakte Feldnamen
  bei der Implementierung verifizieren).

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  Thorest-Calls.
- VET Transfer-In/-Out, Selbst-Transfer wird übersprungen.
- VIP-180-Token-Transfer (inkl. VTHO als "normaler" Token, keine
  Sonderbehandlung im Code).
- Mehrere Einträge pro Transaktion (unterschiedliche `external_id`s).
- `since`-Filterung (client-seitig).
- Pagination.

## Offene Punkte für die Umsetzungsplanung

Keine wesentlichen - die exakte Thorest-API-Feldstruktur muss beim
Implementieren gegen die Live-API verifiziert werden (siehe Hinweis
oben), das ist ein Implementierungsdetail, keine offene
Design-Entscheidung.
