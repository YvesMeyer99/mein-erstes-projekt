# Krypto-Wallet-Dashboard – Backend

## Setup

1. `python -m venv .venv`
2. `.venv/Scripts/pip install -r requirements.txt`
3. `cp .env.example .env` und die eigenen Wallet-Adressen / API-Keys eintragen
   (Kraken-Key **muss** read-only sein - keine Trade-/Auszahlungsrechte!)
4. Datenbank einmalig anlegen: `.venv/Scripts/python -m app.init_db`

## Bitcoin: einzelne Adressen vs. ganze HD-Wallets

`BITCOIN_ADDRESSES` verfolgt einzelne, fest eingetragene Adressen -
praktisch für z.B. eine einzelne Exchange-Einzahladresse, aber
unpraktisch für ein normales Wallet (Ledger, Trezor, AtomicWallet), das
für jede Transaktion eine neue Adresse generiert (HD-Wallet-Standard).

Für ein ganzes HD-Wallet stattdessen `BITCOIN_XPUBS` mit dem **Extended
Public Key** (xpub/ypub/zpub) des Wallets verwenden - zu finden in der
Wallet-Software unter "xpub anzeigen" / "Konto-Details" / "Erweiterte
öffentliche Adresse" (NICHT die einzelne Empfangsadresse, die die
Wallet-App standardmäßig anzeigt). Das Dashboard leitet daraus
automatisch alle bisher genutzten Adressen ab (Gap-Limit-Scanning,
Standard-Grenzwert 20 - wie bei jeder Wallet-Software) und erfasst deren
Transaktionen, inklusive korrekter Behandlung von Wechselgeld
(Change-Adressen): interne Verschiebungen zwischen Adressen desselben
Wallets werden nicht fälschlich als steuerrelevante Transaktion gezählt.

**Wichtig:** der Extended Public Key erlaubt zwar niemandem, deine
Bitcoins auszugeben (das geht nur mit dem privaten Schlüssel), macht
aber deine **gesamte Adresshistorie und alle Kontostände dieses
Wallets einsehbar** für jeden, der ihn kennt. Trotzdem vertraulich
behandeln wie ein Passwort.

**Achtung bei Tippfehlern:** die zugrundeliegende Bibliothek prüft die
Prüfsumme des eingegebenen Schlüssels nicht - ein Tippfehler führt nicht
zu einer Fehlermeldung, sondern lässt das Tool still eine falsche
(vermutlich leere) Adresskette scannen. Den Wert beim Eintragen also
sorgfältig kopieren.

**Nicht überlappend konfigurieren:** trage keine Adresse in
`BITCOIN_ADDRESSES` ein, die auch von einem in `BITCOIN_XPUBS`
konfigurierten Wallet abgedeckt wird - beide Einträge haben zwangsläufig
unterschiedliche Labels, wodurch dieselbe Transaktion doppelt gespeichert
und im Portfolio sowie CSV-Export doppelt gezählt würde.

## Solana

Native SOL- und SPL-Token-Transfers werden automatisch erfasst, sobald
`SOLANA_ADDRESSES` gesetzt ist. Anders als bei Bitcoin generieren
Solana-Wallets (auch Ledger) keine neue Adresse pro Transaktion - jeder
Account hat eine feste Adresse. Für mehrere Accounts (z.B. mehrere
Ledger-Konten) einfach mehrere `label:adresse`-Paare komma-getrennt
eintragen, wie bei `ETHEREUM_ADDRESSES`.

### Bekannte Einschränkung: SPL-Tokens ohne Symbol/CHF-Kurs

SPL-Token-Transfers (z.B. USDC auf Solana) werden vollständig erfasst
(Menge, Zeitpunkt, Richtung), aber die Solana-API liefert kein
Token-Symbol - nur die Mint-Adresse. Im CSV-Export erscheint daher die
rohe Mint-Adresse statt eines lesbaren Namens wie "USDC", und ohne
CHF-Kurs (analog zur bestehenden Einschränkung bei ERC-20-Tokens). Für
die Steuererklärung muss die Mint-Adresse einmalig manuell einem
bekannten Token zugeordnet werden (z.B. über einen Solana-Explorer wie
solscan.io).

## Cardano

Native ADA- und Cardano-Native-Token-Transfers (CNTs) werden automatisch
erfasst, sobald `CARDANO_ADDRESSES` und/oder `CARDANO_STAKE_ADDRESSES`
gesetzt sind.

**Stake-Adresse (empfohlen) vs. einzelne Adresse:** wie Bitcoin können
Cardano-Wallets pro Transaktion neue Zahlungsadressen generieren - eine
einzelne fest eingetragene Adresse (`CARDANO_ADDRESSES`) kann daher
Transaktionen verpassen. `CARDANO_STAKE_ADDRESSES` (die Stake-Adresse
deines Wallets, beginnt mit `stake1...`, zu finden z.B. in AtomicWallet
unter den Cardano-Konto-Details) löst das eleganter als bei Bitcoin: die
verwendete Koios-API kennt bereits alle Zahlungsadressen, die je zu
dieser Stake-Adresse gehört haben, und liefert deren komplette
Transaktionshistorie direkt - keine eigene Adress-Ableitung nötig.

**Wichtig:** die Stake-Adresse macht deine gesamte Adress-/
Transaktionshistorie einsehbar für jeden, der sie kennt (sie erlaubt
aber keinerlei Zugriff auf deine Mittel) - trotzdem vertraulich
behandeln wie ein Passwort.

**Nicht überlappend konfigurieren:** trage keine Adresse in
`CARDANO_ADDRESSES` ein, die auch von einem in `CARDANO_STAKE_ADDRESSES`
konfigurierten Wallet abgedeckt wird - beide Einträge haben zwangsläufig
unterschiedliche Labels, wodurch dieselbe Transaktion doppelt gespeichert
und im Portfolio sowie CSV-Export doppelt gezählt würde (dieselbe
Einschränkung wie bei `BITCOIN_ADDRESSES`/`BITCOIN_XPUBS`).

### Bekannte Einschränkung: Native Tokens ohne Symbol/CHF-Kurs/Dezimalstellen

Cardano-Native-Tokens (z.B. Stablecoins, NFT-nahe Assets) werden
vollständig erfasst (Menge, Zeitpunkt, Richtung), aber ohne lesbaren
Namen (nur Policy-ID + Asset-Name als roher Bezeichner), ohne CHF-Kurs,
und **ohne Dezimalstellen-Anpassung** (Cardano hat anders als bei
SPL-Tokens kein protokollseitiges Decimals-Feld - die Menge erscheint
als rohe Ganzzahl). Für die Steuererklärung muss der Bezeichner einmalig
manuell einem bekannten Token zugeordnet werden (z.B. über einen
Cardano-Explorer wie cardanoscan.io).

## VeChain

Native VET- und VIP-180-Token-Transfers (VeChains ERC-20-Äquivalent,
inkl. expliziter VTHO-Transfers) werden automatisch erfasst, sobald
`VECHAIN_ADDRESSES` gesetzt ist. VeChain-Adressen sind fest (dasselbe
Adressschema wie Ethereum) - keine Adressrotation wie bei Bitcoin/
Cardano, eine Adresse pro Konto reicht.

**Keine Gebühren-Erfassung:** VeChains Netzwerkgebühr wird in VTHO
bezahlt - einem komplett anderen Asset als der transferierte Wert (VET
oder ein VIP-180-Token). Die Gebühr ist daher nie im gemeldeten Betrag
verflochten (anders als bei Bitcoin). VTHO, das rein als Netzwerkgebühr
verbraucht wird (nicht explizit transferiert), wird **nicht** erfasst -
nur explizite VTHO-*Transfers* (z.B. jemand sendet dir VTHO) werden wie
jeder andere VIP-180-Token erfasst.

### Bekannte Einschränkung: VIP-180-Tokens ohne Symbol/CHF-Kurs, feste Dezimalstellen-Annahme

VIP-180-Token-Transfers werden vollständig erfasst (Menge, Zeitpunkt,
Richtung), aber ohne lesbaren Namen (nur die Contract-Adresse als roher
Bezeichner) und ohne CHF-Kurs (analog zur bestehenden Einschränkung bei
ERC-20/SPL-Tokens). Zusätzlich wird für **alle** VIP-180-Tokens
pauschal von **18 Dezimalstellen** ausgegangen (wie bei VET/VTHO und
der überwiegenden Mehrheit der VeChain-Ökosystem-Tokens) - ein seltener
Token mit abweichender Dezimalstellen-Zahl würde falsch skaliert
angezeigt. Für die Steuererklärung im Zweifel gegen einen
VeChain-Explorer wie vechainstats.com verifizieren.

## Unterstützte EVM-Chains

Seit Phase 2a werden neben Ethereum automatisch fünf weitere EVM-Chains
für dieselbe(n) in `ETHEREUM_ADDRESSES` konfigurierte(n) Adresse(n)
mitsynchronisiert - keine zusätzliche Konfiguration nötig:

- Ethereum
- Optimism
- BNB Smart Chain (BSC)
- Polygon
- Base
- Arbitrum One

Alle sechs laufen über Etherscans vereinheitlichte Multi-Chain-API mit
demselben `ETHERSCAN_API_KEY`. Sowohl native Coin-Transfers (ETH, BNB,
MATIC, ...) als auch ERC-20-Token-Transfers (z.B. USDT, USDC) werden auf
allen sechs Chains erfasst.

## Coinbase

Zusätzlich zu Bitcoin/EVM-Chains/Kraken wird automatisch dein Coinbase-App-
Account (Retail, nicht Advanced Trade) mitsynchronisiert, sobald
`COINBASE_API_KEY_NAME` und `COINBASE_API_PRIVATE_KEY` gesetzt sind. Alle
Krypto-Konten (BTC, ETH, ...) werden automatisch erkannt - keine manuelle
Konten-Liste nötig. Fiat-Konten (EUR, CHF, USD, GBP, JPY, CAD, AUD) werden
bewusst übersprungen (auch keine Transaktions-Abfrage dafür), da sie für
die Krypto-Steuerbetrachtung nicht relevant sind und ihre Buy/Sell-Zeilen
sonst mit falschem Vorzeichen im Portfolio landen könnten.

**Wichtig beim Anlegen des API-Keys:**
- CDP Secret API Key mit **ECDSA-Schlüsseltyp** anlegen (nicht den seit
  2025 defaultmäßigen Ed25519-Key - der wird von dieser API nicht
  unterstützt).
- Nur die Lese-Scopes `wallet:accounts:read` und
  `wallet:transactions:read` vergeben - keine Trade-/Sende-/
  Auszahlungsrechte.

### Bekannte Einschränkung: ERC-20-Token werden nicht CHF-bewertet

ERC-20-Token-Transfers werden zwar vollständig erfasst (Menge, Sender/
Empfänger, Zeitstempel), aber **nicht automatisch in CHF bewertet**. Die
CHF-Preisermittlung (`COINGECKO_ID_MAP` in `app/prices/coingecko.py`) kennt
aktuell nur vier native Assets: BTC, ETH, BNB und MATIC. Für alle anderen
Token - inklusive der oben genannten Beispiele USDT und USDC - gibt es
keine Preiszuordnung. Solche Transaktionen laufen ohne Fehler durch den
Sync, erscheinen im CSV-Export aber mit leerem `Kurs CHF`/`Wert CHF` und
müssen für die Steuererklärung manuell bewertet werden.

## MEXC

Zusätzlich zu Bitcoin/EVM-Chains/Kraken/Coinbase wird dein MEXC-Account
mitsynchronisiert, sobald `MEXC_API_KEY` und `MEXC_API_SECRET` gesetzt
sind. Ein-/Auszahlungen werden automatisch erfasst - keine Konfiguration
nötig.

**Trades brauchen manuelle Konfiguration:** MEXC bietet keinen "alle
Trades"-Endpunkt - pro Abfrage muss ein konkretes Handelspaar angegeben
werden. Trage in `MEXC_TRADING_PAIRS` jedes Paar ein, das du handelst
(Format `SYMBOL:BASE:QUOTE`, z.B. `BTCUSDT:BTC:USDT`). Ohne konfigurierte
Paare werden nur Ein-/Auszahlungen erfasst, keine Trades.

**Wichtige Einschränkung: nur die letzten 30 Tage.** MEXCs Trade-API
liefert grundsätzlich nur Trades der letzten 30 Tage, unabhängig vom
Sync-Zeitpunkt. Synchronisiere daher **mindestens einmal im Monat**, um
keine Trades zu verpassen. Ältere Trade-Historie musst du einmalig per
CSV-Export auf der MEXC-Webseite (unterstützt bis zu 3 Jahre) manuell
nachtragen - das kann dieses Tool nicht automatisch abrufen.

## Binance

Zusätzlich zu Bitcoin/EVM-Chains/Kraken/Coinbase/MEXC wird dein Binance-
Account mitsynchronisiert, sobald `BINANCE_API_KEY` und
`BINANCE_API_SECRET` gesetzt sind. Ein-/Auszahlungen werden automatisch
erfasst - keine Konfiguration nötig. Binance erlaubt pro Abfrage nur ein
90-Tage-Fenster; das Tool paginiert das intern automatisch, du merkst
davon nichts.

**Erster Sync:** Ohne Zeitangabe liefert Binance bei Ein-/Auszahlungen
nur die letzten 90 Tage. Setze optional `BINANCE_SYNC_START` (Format
`YYYY-MM-DD`, z.B. dein Konto-Erstellungsdatum) als Startpunkt für den
allerersten Sync. Ohne diese Angabe werden die letzten 5 Jahre
abgedeckt.

**Trades brauchen manuelle Konfiguration:** wie bei MEXC bietet Binance
keinen "alle Trades"-Endpunkt - pro Abfrage muss ein konkretes
Handelspaar angegeben werden. Trage in `BINANCE_TRADING_PAIRS` jedes
Paar ein, das du handelst (Format `SYMBOL:BASE:QUOTE`, z.B.
`BTCUSDT:BTC:USDT`). Ohne konfigurierte Paare werden nur
Ein-/Auszahlungen erfasst, keine Trades.

**Kein 30-Tage-Limit bei Trades:** anders als bei MEXC ist bei Binance
die komplette Handelshistorie über die API abrufbar - kein monatlicher
Zwangs-Sync nötig, um Trades nicht zu verpassen.

## Server starten

```bash
.venv/Scripts/uvicorn app.main:app --reload
```

Läuft danach auf `http://127.0.0.1:8000`. `uvicorn`'s CLI default host is `127.0.0.1` (localhost-only) — do NOT add `--host 0.0.0.0`, since this app has no authentication and is designed to run locally only.

## Frontend

Ein React-Frontend für dieses Backend liegt unter `../frontend/` - siehe
`../frontend/README.md` für Setup. Das Backend muss zuerst laufen (siehe
oben), danach das Frontend separat starten. CORS ist auf die
Vite-Dev-Server-Origins (`http://localhost:5173`, `http://127.0.0.1:5173`)
beschränkt - andere Origins werden vom Backend nicht akzeptiert.

## Manueller Smoke-Test

1. `curl -X POST http://127.0.0.1:8000/api/sync` - stößt Sync für alle konfigurierten
   Wallets/Accounts an, gibt pro Quelle `status: ok` oder `status: error` zurück
2. `curl http://127.0.0.1:8000/api/portfolio` - aktuelle Bestände
3. `curl http://127.0.0.1:8000/api/transactions` - alle Transaktionen
4. `curl http://127.0.0.1:8000/api/export -o test.csv` - CSV-Export prüfen

## Tests

```bash
.venv/Scripts/pytest -v
```

Alle Tests laufen gegen gemockte HTTP-Antworten (`responses`) und eine
In-Memory-SQLite-DB - keine echten API-Calls, keine echten Credentials nötig.

## Bekannte Einschränkung: CoinGecko Free-Tier-Preishistorie

Die App nutzt CoinGecko's öffentlichen `/coins/{id}/history`-Endpoint, um
historische CHF-Preise zu Transaktionen zu ermitteln. Auf dem kostenlosen
CoinGecko-Tier liefert dieser Endpoint zuverlässig nur die Preishistorie der
letzten ca. 365 Tage; für ältere Daten kommt teils keine `market_data` zurück
oder die Anfrage schlägt fehl (z.B. 401).

Der Code fängt das ab und liefert in diesem Fall einfach `None`, ohne
abzustürzen oder den Cache zu verunreinigen. Das bedeutet aber: Transaktionen,
die älter als ca. ein Jahr sind, können in der API-Antwort und im
CSV-Export mit leerem/`null` `price_chf` erscheinen. Das ist auf dem
Free-Tier erwartetes Verhalten, kein Bug - ein bezahlter CoinGecko-Plan mit
vollem Historie-Zugriff würde das beheben.
