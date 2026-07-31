# Phase 2a – Weitere EVM-Chains – Design

Datum: 2026-08-01

## Zweck

Erweiterung des in Phase 1 gebauten Krypto-Wallet-Dashboards um fünf
zusätzliche EVM-Chains, sodass native Coins und ERC-20-Token-Transfers auf
allen sechs EVM-Chains gemeinsam erfasst werden. Baut direkt auf dem in
Phase 1 abgeschlossenen Backend auf (siehe
[2026-07-30-krypto-wallet-dashboard-design.md](2026-07-30-krypto-wallet-dashboard-design.md)
und [2026-07-30-backend-phase1.md](../plans/2026-07-30-backend-phase1.md)).

## Umfang

**Chains:** Ethereum (bereits vorhanden, wird auf die neue Architektur
migriert), Polygon, BSC (BNB Smart Chain), Arbitrum, Optimism, Base.

**Neu in Phase 2 (Erweiterung gegenüber Phase 1):** ERC-20-Token-Transfers
werden jetzt mit erfasst (in Phase 1 explizit auf Phase 2 verschoben) – für
alle sechs EVM-Chains, nicht nur für Ethereum.

**Nicht Teil dieses Plans:** Binance, Coinbase, MEXC (Plan 2b, folgt danach).

## API-Ansatz: Etherscan V2 Multi-Chain-API

Etherscan bietet eine vereinheitlichte Multi-Chain-API: ein einziger
API-Key (`ETHERSCAN_API_KEY`, bereits aus Phase 1 vorhanden) funktioniert
für alle unterstützten Chains. Der einzige Unterschied zwischen den Chains
ist der `chainid`-Query-Parameter:

| Chain | chainid |
|---|---|
| Ethereum | 1 |
| Optimism | 10 |
| BSC | 56 |
| Polygon | 137 |
| Base | 8453 |
| Arbitrum One | 42161 |

Endpunkt-Basis bleibt für alle Chains `https://api.etherscan.io/v2/api`
(statt der alten, chain-spezifischen Domains wie `polygonscan.com`).

## Architektur-Änderung

Der bestehende `EthereumAdapter` (Phase 1) wird zu einem parametrisierten
`EvmAdapter` verallgemeinert:

```python
class EvmAdapter(TransactionAdapter):
    source_type = "chain"

    def __init__(self, account_label, address, api_key, chain_id, chain_name, native_asset):
        ...
```

- `source_name` wird pro Instanz gesetzt (z.B. `"ethereum"`, `"polygon"`,
  `"bsc"`, `"arbitrum"`, `"optimism"`, `"base"`) statt als Klassenattribut,
  da eine Klasse jetzt sechs verschiedene Chains bedienen kann.
- `factory.build_adapters_from_config()` erzeugt aus **derselben**
  `ETHEREUM_WALLETS`-Adressliste sechs `EvmAdapter`-Instanzen (eine je
  Chain) statt bisher einer `EthereumAdapter`-Instanz. Keine neue
  Konfiguration nötig – dieselbe(n) Adresse(n), die schon für Ethereum
  konfiguriert sind, gelten automatisch für alle sechs Chains.
- Die alte `app/adapters/ethereum.py` (`EthereumAdapter`) wird durch
  `app/adapters/evm.py` (`EvmAdapter`) ersetzt; Tests werden entsprechend
  migriert.

## Datenmodell-Erweiterung: ERC-20-Tokens

Etherscans `tokentx`-Action liefert Token-Transfers inkl. `tokenSymbol` und
`tokenDecimal` direkt in der Antwort – kein zusätzliches Preis- oder
Metadaten-Lookup nötig, um den Transfer zu normalisieren.

- Für jede Chain werden zwei Etherscan-Actions abgefragt: `txlist` (native
  Coin, wie in Phase 1) und `tokentx` (ERC-20-Transfers).
- Normalisierung: `asset` = `tokenSymbol` aus der API-Antwort (z.B.
  `"USDT"`, `"USDC"`), `amount` = `value / 10**tokenDecimal`.
- `tx_type` (`transfer_in`/`transfer_out`) wird wie bei nativen Transfers
  durch Vergleich von `from`/`to` mit der eigenen Adresse bestimmt.
- Gas-Gebühren bei Token-Transfers werden immer im nativen Coin der Chain
  bezahlt (nicht im Token selbst) – die Gebühr wird daher nur bei
  nativen-Coin-Transaktionen erfasst (wie in Phase 1), nicht dupliziert bei
  Token-Transfers auf derselben Transaktion.
- Keine Änderung an `app/models.py` nötig – `asset` ist bereits ein freies
  String-Feld, Token-Symbole passen ohne Schema-Änderung hinein.

## Pagination

Die in Phase 1 für den Ethereum-Adapter gebaute `page`/`offset`-Pagination
(Etherscan-Style, `PAGE_SIZE=1000`) wird unverändert übernommen und für
beide Actions (`txlist` und `tokentx`) sowie alle sechs Chains verwendet.

## Fehlerbehandlung

Wie in Phase 1: jeder Adapter (jetzt sechs statt einer) läuft isoliert im
Sync-Loop – schlägt eine Chain fehl (z.B. Rate-Limit), blockiert das nicht
die anderen fünf Chains oder Kraken.

## Tests

- Unit-Tests für `EvmAdapter` mit gemockten Etherscan-V2-Antworten,
  parametrisiert über mehrere Chains (mind. 2 Chains getestet, um zu
  verifizieren, dass `chainid` korrekt durchgereicht wird und
  `source_name` korrekt pro Instanz gesetzt ist).
- Separate Tests für `txlist`- und `tokentx`-Normalisierung.
- Migrierte/angepasste Tests für den bisherigen `EthereumAdapter`-Testfall
  (jetzt als ein Spezialfall von `EvmAdapter` mit `chain_id=1`).

## Offene Punkte für die Umsetzungsplanung

Keine – Design wurde durchgesprochen und bestätigt.
