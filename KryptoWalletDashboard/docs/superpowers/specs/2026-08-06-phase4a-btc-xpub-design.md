# Phase 4a – Bitcoin-xpub-Scanning – Design

Datum: 2026-08-06

## Zweck

Erweiterung des bestehenden `BitcoinAdapter`: statt (nur) einzelne, fest
konfigurierte Adressen zu erfassen, soll optional ein **xpub/ypub/zpub**
(Extended Public Key eines HD-Wallets, z.B. von Ledger, Trezor,
AtomicWallet) angegeben werden können. Der Adapter leitet daraus
automatisch alle bisher genutzten Adressen ab ("Gap-Limit-Scanning",
Standard bei HD-Wallets) und erfasst deren Transaktionen - ohne dass der
Nutzer jede einzelne, pro Transaktion neu generierte Adresse manuell
eintragen muss.

**Auslöser:** Nutzer hat eine einzelne Ledger-Adresse eingetragen, die
laut Wallet "seine" Bitcoin-Adresse ist - tatsächlich aber nur die
nächste unbenutzte Empfangsadresse eines HD-Wallets war, während die
echten Transaktionen auf anderen, abgeleiteten Adressen liegen.

## Hintergrund: warum ein xpub allein nicht reicht

- Blockstream.info (die bereits genutzte API, siehe `app/adapters/
  bitcoin.py`) hat **keinen xpub-Endpunkt** - nur `/address/:address/*`.
  Verifiziert gegen die aktuelle Esplora-API-Doku
  ([Blockstream/esplora API.md](https://github.com/Blockstream/esplora/blob/master/API.md)),
  Stand 2026-08-06.
- Adressen müssen daher **client-seitig aus dem xpub abgeleitet** und
  dann einzeln (wie bisher) über die bestehenden Endpunkte abgefragt
  werden.
- Ein xpub allein legt nicht fest, wie viele Adressen "dazugehören" -
  HD-Wallets generieren theoretisch unendlich viele. Der Standard-Ansatz
  (BIP44/49/84, von jeder Wallet-Software verwendet) ist **Gap-Limit-
  Scanning**: Adressen werden nacheinander abgeleitet (Index 0, 1, 2, ...)
  und abgefragt; sobald **20 aufeinanderfolgende Adressen ohne jede
  Transaktionshistorie** gefunden wurden, wird das Scannen für diese
  Kette gestoppt (Standardwert, von praktisch jeder Wallet-Software
  verwendet).
- Ein xpub hat zwei Ableitungsketten: **Empfang** (`m/0/i`) und
  **Wechselgeld/Change** (`m/1/i`) - beide werden unabhängig
  gescannt, da Change-Adressen ebenfalls Transaktionen enthalten
  (abgehende Zahlungen erzeugen Change-UTXOs auf einer neuen
  Change-Adresse).

## Adressformat-Erkennung

Der Präfix des Extended Public Key legt das Adressformat fest:

| Präfix  | Standard | Adressformat                          |
|---------|----------|----------------------------------------|
| `xpub`  | BIP44    | Legacy P2PKH (`1...`)                  |
| `ypub`  | BIP49    | Nested-Segwit P2SH-P2WPKH (`3...`)     |
| `zpub`  | BIP84    | Native-Segwit P2WPKH (`bc1...`)        |

Alle drei werden unterstützt, da alle drei bei gängigen Wallets (Ledger
Live, Trezor Suite, AtomicWallet) vorkommen - Ledger Live nutzt seit
einigen Jahren standardmäßig native Segwit (`zpub`), ältere Wallets/
Konfigurationen oft noch `xpub`/`ypub`.

## Bibliothek

**Neue Abhängigkeit: `bitcoinlib`** (PyPI, aktiv gepflegt,
[1200wd/bitcoinlib](https://github.com/1200wd/bitcoinlib)). Übernimmt:
- Parsen von xpub/ypub/zpub-Strings (`HDKey(import_key=...)`)
- BIP32-Kindschlüssel-Ableitung (`key_for_path("m/0/5")` o.ä.)
- Adress-Encoding für alle drei Formate (Base58 für Legacy/P2SH-Segwit,
  Bech32 für Native-Segwit) passend zum erkannten Präfix

**Hinweis für die Umsetzung:** `bitcoinlib`s genaue API (ob das
Adressformat automatisch aus dem xpub/ypub/zpub-Präfix erkannt wird, oder
ob `witness_type`/`encoding` beim `HDKey(...)`-Aufruf explizit mitgegeben
werden muss) war zum Recherchezeitpunkt nicht abschließend klar - vor der
Implementierung kurz gegen die installierte Version prüfen (z.B. via
`HDKey(import_key="<Test-zpub>").address()` und Vergleich mit einem
bekannten Adress-Ableitungs-Tool). Die *Absicht* (korrektes
Adressformat automatisch passend zum Präfix) ist maßgeblich, nicht die
exakte Bibliotheks-Aufrufsyntax.

## Normalisierung

Identisch zum bestehenden `BitcoinAdapter`: pro gefundener, "genutzter"
Adresse werden deren Transaktionen über dieselbe vin/vout-Netto-Logik
normalisiert wie bisher (`tx_type="transfer_in"`/`"transfer_out"`,
`asset="BTC"`, Gebühren-Erkennung). Diese Logik wird **nicht
dupliziert**, sondern aus dem bestehenden `BitcoinAdapter` in eine
gemeinsame Hilfsfunktion extrahiert (z.B.
`normalize_bitcoin_txs_for_address(address, raw_txs, since) ->
list[NormalizedTransaction]`), die sowohl vom bestehenden
Einzel-Adress-Pfad als auch vom neuen xpub-Pfad verwendet wird.

`external_id` bleibt die Transaktions-ID (`txid`) - da eine Transaktion
theoretisch mehrere Adressen desselben xpubs gleichzeitig betreffen
könnte (z.B. Empfang auf einer Adresse und Wechselgeld auf einer
Change-Adresse in derselben Transaktion), wird über ein `set` bereits
gesehener `txid`s innerhalb eines Sync-Laufs dedupliziert, bevor die
Ergebnisliste zurückgegeben wird - die bestehende `external_id`-Dedup-
Prüfung in `sync.py` würde das zwar auch beim nächsten Sync abfangen,
aber innerhalb *eines* Laufs sonst zu einer fälschlich doppelten
`new_transactions`-Zählung führen können.

## Gap-Limit-Scanning & Sync-Verhalten

- **Kein Caching der entdeckten Adressen zwischen Syncs.** Jeder Sync
  scannt das Gap-Limit für beide Ketten (Empfang/Change) erneut von
  Adress-Index 0 an, komplett neu. Das ist bewusst einfach gehalten
  (kein neuer DB-State für "welche Adressen kennen wir schon nötig") -
  analog zum bereits etablierten Muster bei Binance-Trades ("bei jedem
  Sync alles neu abfragen, auf die bestehende `external_id`-Dedup-Prüfung
  in `sync.py` verlassen"). Mehr API-Calls pro Sync, aber korrekt und
  ohne neue Komplexität. Für ein Ein-Nutzer-Lokal-Tool mit
  gelegentlichem manuellem Sync unproblematisch.
- **Gap-Limit = 20** (fester Wert, Branchenstandard, nicht konfigurierbar
  - eine Konfigurationsoption dafür wäre YAGNI für dieses Tool).
- Für jede der beiden Ketten (Empfang `m/0/i`, Change `m/1/i`): Adressen
  werden nacheinander abgeleitet und über
  `GET /address/:address` (liefert u.a. `chain_stats.tx_count`) auf
  Nutzung geprüft. Sobald 20 aufeinanderfolgende unbenutzte Adressen
  gefunden wurden, stoppt das Scannen dieser Kette. "Benutzt" = Adresse
  hat mindestens eine Transaktion (`tx_count > 0`), unabhängig vom
  aktuellen Guthaben (auch leergeräumte Adressen zählen als benutzt).
- Für jede als benutzt erkannte Adresse werden anschließend die vollen
  Transaktionsdetails wie beim bestehenden Einzel-Adress-Adapter
  abgerufen und normalisiert.

## Konfiguration

Neue, zur bestehenden `BITCOIN_ADDRESSES` parallele Variable:

```
BITCOIN_XPUBS=ledger:zpub6jftahH1...
```

Format `label:xpub_oder_ypub_oder_zpub`, komma-getrennt für mehrere
HD-Wallets (analog zum bestehenden `parse_wallets()`-Muster, das
wiederverwendet werden kann - ein xpub/ypub/zpub-String enthält keine
Kommas oder Doppelpunkte, ist also mit dem bestehenden Parser
kompatibel, ohne dass eine neue Parsing-Funktion nötig ist).

Beide Konfigurationswege (`BITCOIN_ADDRESSES` für Einzeladressen,
`BITCOIN_XPUBS` für HD-Wallets) können unabhängig voneinander und
gleichzeitig genutzt werden - kein Ersetzen des bestehenden Wegs, da
manche Nutzer evtl. gezielt nur eine einzelne, bekannte Adresse tracken
wollen (z.B. eine Exchange-Einzahladresse), nicht ein ganzes HD-Wallet.

`account_label` (aus `label:...`) wird als `account_label` der erzeugten
Transaktionen verwendet - identisch zum bestehenden Einzel-Adress-Pfad,
sodass in der Transaktions-Tabelle des Frontends ersichtlich bleibt, aus
welchem Wallet eine Transaktion stammt.

## Architektur

Neue Datei `app/adapters/bitcoin_xpub.py` mit `BitcoinXpubAdapter`, die
denselben `TransactionAdapter`-Interface wie `BitcoinAdapter` implementiert
(`source_type="chain"`, `source_name="bitcoin"` - gleicher `source_name`
wie der bestehende Adapter, da es sich fachlich um dieselbe Chain handelt;
Unterscheidung erfolgt über `account_label`). Die gemeinsame vin/vout-
Normalisierungslogik wird aus `app/adapters/bitcoin.py` in eine
Modul-Funktion extrahiert und von beiden Adaptern importiert - kein
Duplizieren der bestehenden, bereits getesteten Logik.

`app/adapters/factory.py` baut zusätzlich zu den bestehenden
`BitcoinAdapter`-Instanzen (eine pro `BITCOIN_ADDRESSES`-Eintrag) je eine
`BitcoinXpubAdapter`-Instanz pro `BITCOIN_XPUBS`-Eintrag.

## Tests

- Unit-Tests mit gemockten HTTP-Antworten (`responses`), keine echten
  API-Calls, kein echtes xpub im Test-Code (Test-Fixtures nutzen ein
  öffentlich bekanntes Test-Vektor-xpub aus der BIP32-Testsuite, keine
  echten Nutzer-Daten).
- Gap-Limit-Scanning: Test mit z.B. 3 benutzten Empfangsadressen gefolgt
  von 20 unbenutzten - Scan stoppt korrekt, Adresse 24+ wird nicht mehr
  abgefragt.
- Beide Ketten (Empfang/Change) unabhängig getestet.
- Adressformat-Erkennung: je ein Test-xpub/ypub/zpub, prüft dass die
  abgeleiteten Adressen im erwarteten Format vorliegen (`1...`/`3...`/
  `bc1...`).
- Dedup bei Transaktionen, die mehrere Adressen desselben xpubs
  betreffen (z.B. Empfang + Change in derselben Transaktion).
- Extraktion der gemeinsamen Normalisierungslogik: bestehende
  `test_bitcoin_adapter.py`-Tests müssen unverändert weiterlaufen
  (Regressionsschutz für den Refactor).

## Offene Punkte für die Umsetzungsplanung

Keine wesentlichen - die genaue `bitcoinlib`-API-Aufrufsyntax muss beim
Implementieren kurz gegen die installierte Version verifiziert werden
(siehe Hinweis oben), das ist ein Implementierungsdetail, keine offene
Design-Entscheidung.
