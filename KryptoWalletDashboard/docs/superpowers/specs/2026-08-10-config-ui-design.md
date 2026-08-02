# Konfigurations- und Account-Verwaltungs-UI – Design

Datum: 2026-08-10

## Zweck

Zwei neue Seiten im Frontend:

1. **Konfiguration**: alle Wallet-Adressen und API-Keys, die aktuell in
   `.env` stehen, direkt im Browser bearbeiten. Speichern schreibt die
   `.env`-Datei und lädt die Konfiguration im laufenden Backend-Prozess
   neu, sodass der nächste Sync die neuen Werte nutzt - **kein
   Server-Neustart nötig**.
2. **Accounts verwalten**: Liste aller in der DB vorhandenen Accounts
   (Quelle + Account-Label, Anzahl Transaktionen, letzter Sync-Status),
   mit gezielter Auswahl und Löschung - unabhängig davon, ob der Account
   noch in der `.env` konfiguriert ist.

## Entscheidungen (mit Nutzer abgestimmt)

- **Secrets werden nie an das Frontend gesendet.** `GET /api/config`
  liefert für Secret-Felder (Kraken/Coinbase/MEXC/Binance API-Secrets,
  Coinbase Private Key) immer einen leeren String, unabhängig vom
  tatsächlich gespeicherten Wert. Beim Speichern gilt: ein leeres
  Secret-Feld bedeutet "unverändert lassen" (der bestehende Wert in der
  `.env` bleibt stehen), ein nicht-leerer Wert überschreibt ihn. Für
  alle anderen (sichtbaren) Felder bedeutet ein leeres Feld dagegen
  "bewusst löschen", da der Nutzer den aktuellen Wert ja sieht.
- **Strukturiertes Formular**, kein Rohtext-Editor der ganzen `.env`.
  Pro Chain/Exchange ein Abschnitt mit den zugehörigen Feldern - ein
  Eingabefeld pro `.env`-Variable (z.B. ein Textfeld für
  `SOLANA_ADDRESSES`, in das weiterhin das bekannte
  `label:adresse,label:adresse`-Format eingegeben wird), keine
  dynamische Multi-Zeilen-Adressliste pro Wallet - das wäre für den
  Umfang dieser Anfrage Überengineering.
- **Löschen mit gezielter Auswahl**, nicht nur der Trigger für den
  bereits existierenden `/api/prune`-Endpunkt (der ausschliesslich
  Accounts löscht, die *nicht mehr* konfiguriert sind). Die neue Seite
  zeigt **alle** Accounts an (auch weiterhin konfigurierte) und erlaubt,
  gezielt einzelne auszuwählen und zu löschen - z.B. um eine
  Testkonfiguration aufzuräumen, ohne die `.env` anzufassen.
- **`DATABASE_URL` ist nicht Teil der UI.** Sie bestimmt die
  SQLAlchemy-Engine-Verbindung, die bereits beim Prozessstart aufgebaut
  wird - ein Live-Wechsel wäre ohne Neustart ohnehin nicht wirksam und
  gehört konzeptionell nicht zu "Wallet-Adressen und API-Keys".

## Technischer Kern: Config-Reload ohne Neustart

`app/config.py` liest aktuell alle Werte einmalig beim Modul-Import als
Modul-Level-Konstanten (`BITCOIN_WALLETS = parse_wallets(...)`, usw.).
`app/adapters/factory.py` greift bereits über `config.BITCOIN_WALLETS`
usw. (Attribut-Zugriff auf das Modul-Objekt, nicht `from app.config
import BITCOIN_WALLETS`) darauf zu - das ist bereits reload-freundlich,
da eine Neuzuweisung von `config.BITCOIN_WALLETS = ...` zur Laufzeit
sofort bei jedem folgenden `config.BITCOIN_WALLETS`-Zugriff sichtbar
wird, ohne `factory.py` selbst anzufassen. Ebenso greifen die
bestehenden `test_factory.py`-Tests bereits über
`monkeypatch.setattr(config, "BITCOIN_WALLETS", ...)` zu - funktioniert
nach dem Refactoring unverändert weiter.

Die Lösung: die bestehenden Modul-Level-Zuweisungen in eine interne
`_load_all_from_env()`-Funktion verschieben (führt exakt dieselben
Zuweisungen wie bisher aus, nur wiederholbar), die einmalig beim
Modul-Import UND zusätzlich über eine neue öffentliche
`reload_config()`-Funktion aufgerufen wird. `reload_config()` ruft
zuerst `load_dotenv(ENV_FILE_PATH, override=True)` (python-dotenv lädt
sonst nur Variablen, die noch nicht in `os.environ` gesetzt sind -
`override=True` ist zwingend nötig, damit geänderte Werte tatsächlich
ankommen), dann `_load_all_from_env()`.

## Neues Modul: `app/env_file.py`

Kapselt das Lesen/Schreiben der `.env`-Datei selbst (nicht über
`os.environ`, sondern direkt von der Datei) plus die Feld-Metadaten für
die UI:

- `CONFIG_FIELDS: list[ConfigField]` - eine geordnete Liste aller
  editierbaren Felder mit `name` (env-Variablenname), `section`
  (Anzeige-Gruppe), `label`, `is_secret`, `hint`. Einzige Quelle der
  Wahrheit für welche Felder die UI anzeigt.
- `read_config_values(path=ENV_FILE_PATH) -> dict[str, str]` - aktueller
  Wert pro bekanntem Feld direkt aus der Datei gelesen (nicht aus
  `os.environ`, damit auch ein noch nicht neu geladener Zustand korrekt
  widergespiegelt wird). Secret-Felder immer `""`.
- `write_config_values(updates: dict[str, str], path=ENV_FILE_PATH) ->
  None` - schreibt die Datei zeilenweise neu: bekannte `KEY=...`-Zeilen
  werden in-place ersetzt (alle anderen Zeilen, inkl. Kommentare, bleiben
  unverändert), neue Felder werden ans Ende angehängt. Secret-Felder mit
  leerem `updates`-Wert werden übersprungen (nicht überschrieben) - alle
  anderen Felder werden auch mit leerem Wert geschrieben (bewusstes
  Löschen).

## Account-Verwaltung: Erweiterung von `app/prune.py`

- `list_accounts(session, adapters=None) -> list[dict]` - jedes
  distinct `(source_name, account_label)`-Paar aus `Transaction` UND
  `SyncState` (Union, falls ein Account einen Sync-Fehler ohne jemals
  eine Transaktion geschrieben zu haben hat), mit
  `transaction_count`, `last_synced_at`, `last_error`, und
  `is_configured` (informativ, blockiert die Löschung nicht).
- `delete_accounts(session, pairs: list[tuple[str, str]], dry_run=False)
  -> list[dict]` - generische Lösch-Primitive für beliebige, explizit
  ausgewählte Account-Paare (unabhängig von der `.env`). Das bestehende
  `prune_stale_accounts()` wird darauf umgestellt (berechnet nur noch
  die Stale-Menge und delegiert die eigentliche Löschung), Verhalten
  bleibt exakt gleich (bestehende Tests unverändert gültig).

## Neue Endpunkte

- `GET /api/config` - `{"fields": [{name, section, label, is_secret,
  hint, value}, ...]}`.
- `POST /api/config` - Body `{"BITCOIN_XPUBS": "...", ...}` (Feldname ->
  neuer Wert, nur geänderte oder alle Felder). Schreibt die Datei, ruft
  `reload_config()` auf, gibt `{"status": "ok"}` zurück.
- `GET /api/accounts` - `{"accounts": [...]}` (siehe `list_accounts`).
- `POST /api/accounts/delete` - Body `{"accounts": [{"source_name":
  "...", "account_label": "..."}, ...]}`, liefert dieselbe Report-Form
  wie `/api/prune`.

## Frontend

- `Konfiguration.tsx`: lädt `GET /api/config`, rendert pro `section`
  eine Gruppe mit einem Eingabefeld pro Feld (Secret-Felder als
  `type="password"`, immer leer vorbefüllt, mit Platzhaltertext
  "unverändert lassen, um bestehenden Wert zu behalten"). "Speichern"
  sendet den kompletten Formular-Zustand als `POST /api/config` - das
  Backend übernimmt die Secret-vs-Nicht-Secret-Semantik, kein
  Diffing im Frontend nötig.
- `Accounts.tsx`: lädt `GET /api/accounts`, Tabelle mit Checkbox pro
  Zeile, "Ausgewählte löschen"-Button mit `window.confirm()`-Bestätigung
  vor dem eigentlichen `POST /api/accounts/delete` (destruktive Aktion,
  kein Undo).
- `Sidebar.tsx`: zwei neue Einträge, "Konfiguration" und "Accounts".

## Sicherheitsüberlegung

Die App hat bereits keine Authentifizierung und ist explizit als
"nur lokal" dokumentiert (README, CORS auf die Vite-Dev-Origins
beschränkt). Die neuen Endpunkte ändern daran nichts - sie erweitern
lediglich, WAS lokal ohne Auth änderbar ist (vorher: nur Sync
auslösen/Daten lesen; neu: `.env` schreiben, DB-Zeilen löschen). Das
passt zum bestehenden Vertrauensmodell dieses Ein-Personen-Tools; eine
Authentifizierung einzuführen wäre Scope-Creep für diese Anfrage.
