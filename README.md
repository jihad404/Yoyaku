# Yoyaku

Telegram-Bot, der freie Termine bei der **Stadt Duisburg** überwacht und Nutzer
benachrichtigt, sobald ein passender Termin online buchbar wird.

Abgedeckt sind alle Dienstleistungen der vier eTermin-Buchungsseiten der Stadt
(insgesamt 96 eTermin-IDs, im Bot 88 Einträge):

| Buchungsseite | Beispiele |
|---|---|
| Bürgerservice (7 Bürger-Service-Stationen) | Personalausweis, Reisepass, An-/Ummeldung, Führerscheinanträge, Führungszeugnis, Fundsachen |
| Fahrerlaubnisbehörde | Umtausch, Ersatz, Internationaler Führerschein, Umschreibung, Taxischein |
| Zulassungsstelle | Neuzulassung, Wiederzulassung, Kennzeichen, Umschreibung |
| Gewerbemeldestelle | Gewerbe an-/ab-/ummelden, Gewerbezentralregister |

Quelle: https://www.duisburg.de/allgemein/fachbereiche/90/terminvereinbarung-buergerservice

## Funktionen

- **Suche per Buttons:** Thema → (Bereich) → Dienstleistung → (Standort) → Zeitraum
- **Stichwortsuche:** einfach ein Wort schicken, z. B. „reisepass“ oder „umzug“
- **Drei Modi:**
  - ⚡ *So früh wie möglich* – meldet, wenn ein früherer Termin als der bisher früheste frei wird
  - 📅 *Bis spätestens …* – meldet neu frei gewordene Termine bis zu einem Datum
  - 🎯 *Bestimmter Tag* – meldet, wenn der Tag frei wird und wenn er wieder wegfällt
- **Standortfilter** beim Bürgerservice (Hamborn, Homberg, Meiderich, Mitte, Rheinhausen, Süd, Walsum)
- Bis zu **5 Suchen** gleichzeitig pro Nutzer
- Benachrichtigungen mit Uhrzeiten, Standort und direktem Buchungslink
- Freischaltung neuer Nutzer durch den Admin

### Befehle

| Befehl | Funktion |
|---|---|
| `/start` | Begrüßung und Hilfe |
| `/register Vorname Nachname TT.MM.JJJJ` | Registrierung (Admin muss freigeben) |
| `/search` | Neue Terminsuche |
| `/status` | Aktive Suchen und aktuell freie Termine |
| `/stop` | Suchen beenden |
| `/pending`, `/approve_<id>` | Admin: offene Registrierungen freigeben |

## Wie es funktioniert

Der Bot fragt die JSON-Schnittstelle ab, über die auch die eTermin-Buchungsseiten
ihre Daten laden (kein Browser, kein Selenium).

- **Prüfintervall:** alle 3 Minuten. Jede Dienstleistung wird pro Runde nur einmal
  abgefragt, egal wie viele Suchen darauf laufen.
- **Nur buchbare Termine:** Der Bot liest die Einstellungen jeder Buchungsseite
  (`/api/settingbs`, z. B. Buchungszeitraum, Vorlaufzeit, Freigabe-Uhrzeit) und die
  Dauer der Dienstleistung und fragt mit genau diesen Parametern – und nur so viele
  Monate, wie der Buchungszeitraum reicht (meist 1–2 Anfragen). Ohne sie liefert
  eTermin auch Zeiten, die online (noch) nicht buchbar sind – etwa Termine des
  Bürgerservice vor der täglichen Freigabe um 16 Uhr oder Termine der
  Fahrerlaubnisbehörde außerhalb ihres 14-Tage-Fensters.
- **Keine Nachrichtenflut:** Derselbe Tag wird pro Suche höchstens alle 2 Stunden
  gemeldet; ein einzelnes leeres Ergebnis (Ladefehler) wird ignoriert.
- **Täglicher Katalogabgleich** um 06:00: Der Admin wird informiert, wenn eTermin
  - Dienstleistungen hinzufügt oder entfernt (➕/➖),
  - eine Dienstleistung zwar noch listet, sie dort aber nicht mehr buchbar ist, z. B.
    „Dies kann ausschließlich im Bürgerservice erledigt werden“ oder ausgeblendete
    Terminwahl (🚫) – Nutzer mit Suchen darauf bekommen einmal einen Hinweis,
  - Name, Hinweistext oder Terminwahl einer Dienstleistung ändert (✏️, einmalig je Änderung).
- **Überwachung:** Ist eine Buchungsseite 3 Runden lang nicht erreichbar, bekommt
  der Admin eine Nachricht (und eine Entwarnung, wenn es wieder geht).

### Projektstruktur

```
run.py                   Einstiegspunkt (Logging, Datenbank, Bot)
config.py                Liest BOT_TOKEN und ADMIN_ID aus .env
logging_setup.py         Log-Datei + Konsole
bot/
  main.py                Handler und Jobs registrieren
  handlers.py            /start, /register, /pending, /approve
  search_flow.py         /search, Button-Navigation, Stichwortsuche
  searches.py            /status, /stop
  errors.py              Zentraler Fehler-Handler
manager/
  checker.py             Prüfrunde und Benachrichtigungen
  evaluate.py            Auswertungslogik je Modus (reine Funktionen)
  messages.py            Nachrichtentexte
  catalog_sync.py        Täglicher Katalogabgleich
scrapers/
  etermin.py             Client für die eTermin-Schnittstelle
  catalog.py             Themen, Dienstleistungen, Standorte, Stichwortsuche
  registry.py            Zugriff mit Zwischenspeicher und Parallelitätsgrenze
database/
  db.py                  SQLite-Schema und Migrationen
  models.py              Datenbankzugriffe
tests/                   pytest, mit echten eTermin-Antworten als Testdaten
```

## Installation (Raspberry Pi)

Voraussetzung: Python **3.10 oder neuer** (getestet mit 3.11 = Raspberry Pi OS
Bookworm und 3.13 = Raspberry Pi OS Trixie).

> Nach einem Betriebssystem-Update mit neuer Python-Version die virtuelle
> Umgebung neu anlegen (`rm -rf venv`, dann die Schritte unten wiederholen).

```bash
git clone git@github.com:jihad404/Yoyaku.git ~/repos/Yoyaku
cd ~/repos/Yoyaku
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # BOT_TOKEN und ADMIN_ID eintragen
python3 run.py          # Testlauf, Abbruch mit Ctrl+C
```

- `BOT_TOKEN` bekommt man von [@BotFather](https://t.me/BotFather).
- `ADMIN_ID` ist die eigene numerische Telegram-ID (z. B. über [@userinfobot](https://t.me/userinfobot)).
  Der Admin schickt danach einmal `/start` an den Bot.

### Als Dienst einrichten (startet automatisch, auch nach Neustart)

```bash
sudo tee /etc/systemd/system/yoyaku.service > /dev/null <<'EOF'
[Unit]
Description=Yoyaku Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/repos/Yoyaku
ExecStart=/home/pi/repos/Yoyaku/venv/bin/python run.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now yoyaku
```

`User` und Pfade bei Bedarf anpassen. Prüfen: `systemctl is-enabled yoyaku` → `enabled`.

### Update

```bash
cd ~/repos/Yoyaku && git pull && sudo systemctl restart yoyaku
```

Hat sich `requirements.txt` geändert, vor dem Neustart die Bibliotheken aktualisieren:

```bash
cd ~/repos/Yoyaku && git pull && venv/bin/pip install -r requirements.txt && sudo systemctl restart yoyaku
```

Neue Spalten in der Datenbank werden beim Start automatisch angelegt.

## Betrieb

### Logs

- **Datei:** `logs/yoyaku.log` (rotiert bei 1 MB, max. 6 MB insgesamt)
- **Journal:** `journalctl -u yoyaku -f`

```bash
tail -f ~/repos/Yoyaku/logs/yoyaku.log
```

Protokolliert werden Prüfrunden (mit Dauer), angelegte/beendete Suchen, gesendete
Benachrichtigungen, eTermin-Fehler und der Katalogabgleich – mit interner
Nutzer-ID, ohne Namen.

### Fehler

Unerwartete Fehler landen mit Traceback im Log und in der Tabelle `error_logs`.
Nutzer bekommen eine Fehlerreferenz, der Admin höchstens alle 10 Minuten eine
Nachricht. Fehler nachschlagen:

```bash
python3 -c "import sqlite3; [print(r) for r in sqlite3.connect('yoyaku.db').execute('SELECT created_at, reference, error_message FROM error_logs ORDER BY id DESC LIMIT 20')]"
```

### Live-Prüfung einer Dienstleistung

Zeigt, was der Bot gerade als buchbar sieht (gleiche Abfrage wie im Bot):

```bash
python3 -m scrapers.etermin personalausweis
python3 -m scrapers.etermin              # listet alle Schlüssel
```

### Katalog pflegen

Meldet der tägliche Abgleich neue oder entfernte Dienstleistungen, wird
`scrapers/catalog.py` angepasst: Eintrag mit Schlüssel, Thema, kurzem Namen,
Buchungsseite, eTermin-ID und Stichwörtern hinzufügen bzw. entfernen.
`tests/test_catalog.py` prüft, dass der Katalog vollständig zu den Testdaten passt.

Ist eine Dienstleistung **umgezogen** (🚫, z. B. Führerscheinanträge seit November 2026
nur noch im Bürgerservice), wird der alte Eintrag aus `_SERVICES` entfernt und in
`MOVED` mit dem neuen Schlüssel eingetragen. Beim nächsten Start stellt der Bot alle
aktiven Suchen darauf um und schreibt den Nutzern einmal, wo jetzt gesucht wird.

## Entwicklung

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Die Tests laufen ohne Netz und ohne Telegram (Fake-Objekte, echte eTermin-Antworten
als Fixtures in `tests/fixtures/`).

Design-Dokument: [docs/superpowers/specs/2026-10-06-alle-termine-design.md](docs/superpowers/specs/2026-10-06-alle-termine-design.md)

## Datenschutz

- `yoyaku.db` (Namen, Geburtsdaten, Telegram-IDs), `.env` und `bot_state.pickle`
  sind in `.gitignore` und gehören **nicht** ins Repository.
- Logs enthalten nur interne Nutzer-IDs.
- Die eTermin-Schnittstelle ist nicht offiziell dokumentiert; der Bot fragt mit
  eigenem User-Agent und höchstens 4 parallelen Anfragen.

## Lizenz

[MIT](LICENSE)
