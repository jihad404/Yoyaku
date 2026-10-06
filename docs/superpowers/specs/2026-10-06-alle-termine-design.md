# Design: Alle Duisburger eTermin-Dienstleistungen im Bot

Stand: 06.10.2026 · Status: freigegeben

## Ziel

Der Bot soll freie Termine für **alle** Dienstleistungen überwachen, die über
https://www.duisburg.de/allgemein/fachbereiche/90/terminvereinbarung-buergerservice
(und die bereits angebundene Zulassungsstelle) buchbar sind — übersichtlich nach
Themen geordnet, mit Stichwortsuche, damit Nutzer schnell zur richtigen
Dienstleistung finden.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Umfang | Alle 4 eTermin-Buchungsseiten (95 Dienstleistungs-IDs) |
| Navigation | Themen → (Unterthema) → Dienstleistung per Inline-Buttons, zusätzlich Freitext-Stichwortsuche |
| Suchen pro Nutzer | Mehrere, max. 5 aktive |
| Modi | „So früh wie möglich“, „Bis spätestens X“, „Bestimmter Tag“ |
| Standort | Beim Bürgerservice optional wählbar (7 Stationen), sonst „Egal“ |
| Katalog | Kuratiert im Code (Ansatz A), täglicher Abgleich mit eTermin, Admin-Hinweis bei Abweichungen |
| Datenquelle | eTermin-JSON-Schnittstelle statt Selenium |

## Datenquelle: eTermin-Schnittstelle

Alle Aufrufe gegen `https://www.etermin.net/api/…` mit Header `webid: <Buchungsseite>`.

- `GET /api/servicegroupservice` → Liste aller Dienstleistungen (`sid`, `s` = Name, `sg` = Gruppe).
- `GET /api/timeslots?date=YYYY-MM-DD&serviceid=…&rangesearch=1&…` → Tage mit freien
  Terminen **vom angegebenen Datum bis Monatsende**. Für 3 Monate Vorschau: 3 Aufrufe.
- `GET /api/timeslots?date=YYYY-MM-DD&serviceid=…&…` (ohne `rangesearch`) → einzelne
  Zeitfenster eines Tages mit `calendarname` (= Standort, z. B.
  `Bürger-Service-Station-Hamborn_Slot2`).

Buchungsseiten (`webid`): `stadt-duisburg` (Bürgerservice), `stadt-duisburg-gewerbe`,
`stadt-duisburg-zul` (Zulassungsstelle), `qterminstadtduisburgstva` (Fahrerlaubnisbehörde).
Buchungslink: `https://www.etermin.net/<webid>?serviceid=<sid>`.

## Komponenten

```
scrapers/etermin.py      Schnittstellen-Client (httpx, async): available_days, slots, list_services
scrapers/catalog.py      Themen, Unterthemen, Dienstleistungen, Standorte, Stichwortsuche
scrapers/registry.py     Zugriff mit 60-s-Cache und Lock pro Anfrage
bot/handlers.py          /start, /register, /pending, /approve
bot/search_flow.py       /search, Button-Navigation, Stichwortsuche, Suche anlegen
bot/searches.py          /status, /stop
manager/evaluate.py      Reine Auswertungslogik pro Modus (ohne I/O)
manager/checker.py       Prüfrunde alle 3 Minuten
manager/catalog_sync.py  Täglicher Katalogabgleich (06:00)
```

`scrapers/duisburg_zulassung.py` und die Abhängigkeit `selenium` entfallen.

## Themen

🪪 Ausweis & Pass · 🏠 Wohnen & Melden · 🚗 Fahrzeug & Zulassung (Unterthemen: Zulassung,
Kennzeichen, Papiere & Umschreibung, Diebstahl & Verlust, Technik, Abmeldung) ·
🚦 Führerschein (Unterthemen: Beantragen, Umtausch & Ersatz, International, Beruf &
Personenbeförderung, Abholung, Sonstiges) · 💼 Gewerbe · 📦 Fundsachen ·
📄 Bescheinigungen & Sonstiges.

Doppelte eTermin-Einträge mit identischem Namen (z. B. „Berichtigung ZB I“ in zwei
Gruppen der Zulassungsstelle) werden zu einem Katalogeintrag zusammengefasst; die
zweite ID wird als Alias geführt, damit der Abgleich sie nicht als „neu“ meldet.

## Bot-Ablauf

`/search` oder Freitext → Thema → (Unterthema) → Dienstleistung → (Standort, nur
Bürgerservice) → Modus → ggf. Datum → Bestätigung mit aktuellem Stand und Buchungslink.
Alle Schritte bearbeiten dieselbe Nachricht, „« Zurück“ überall. Freitext findet bis zu
8 Treffer (Name + Stichwörter, unabhängig von Groß-/Kleinschreibung und Umlautschreibweise).

`/status` listet aktive Suchen als Buttons, ein Tipp zeigt die nächsten freien Tage mit
Uhrzeiten. `/stop` listet Suchen mit [Beenden] und [Alle beenden].

Limits: max. 5 aktive Suchen; identische Suche (Dienstleistung + Standort + Modus + Datum)
wird abgelehnt. Die Befehle `/search_N`, `/search_any`, `/search_date` entfallen.

## Checker

Alle 3 Minuten: jede in aktiven Suchen vorkommende Dienstleistung genau einmal abfragen,
Zeitfenster nur bei Bedarf (Standortfilter, Benachrichtigungstext). Auswertung je Modus:

| Modus | Meldet | Endet |
|---|---|---|
| earliest | neuer frühester Tag < bisher frühester | nie (nur /stop) |
| until | neu frei gewordene Tage ≤ X | wenn X vorbei |
| day | Tag frei geworden / wieder weg (letzteres nur wenn vorher gemeldet) | wenn Tag vorbei |

- Derselbe Tag wird pro Suche höchstens alle 2 Stunden gemeldet.
- Weggefallene Tage nur im Modus `day`.
- Leeres Ergebnis bei vorher bekannten Tagen wird erst nach 2 Runden in Folge übernommen.
- Benachrichtigung mit Uhrzeiten (max. 3 + „weitere“), Standort, Buttons [Jetzt buchen ↗] [Suche beenden].

## Datenbank

`searches` erhält `mode` (`earliest`/`until`/`day`), `location` (Schlüssel oder NULL) und
`state` (JSON: `earliest`, `known`, `notified` {Tag: Zeitstempel}, `day_available`).
`search_type` enthält den Katalog-Schlüssel, `target_date` das Datum für `until`/`day`.
Migration: `duisburg_zulassung` → `wiederzulassung`; mit `target_date` → `day`, sonst
`earliest`; `duisburg_aufenthalt` wird deaktiviert.

## Fehlerbehandlung

- Schnittstellenfehler (15 s Timeout, HTTP-Fehler, unerwartetes Format) → `error_logs`,
  Dienstleistung in dieser Runde überspringen. Nach 3 fehlgeschlagenen Runden pro
  Buchungsseite einmalige Admin-Nachricht, bei Erholung Entwarnung.
- Eigener User-Agent, gemeinsame Verbindung, kurze Pause zwischen Anfragen.
- Veraltete Buttons → freundlicher Hinweis statt Absturz.
- Telegram „Forbidden“ → Suchen des Nutzers beenden.

## Tests

`pytest` (requirements-dev.txt). Echte eTermin-Antworten vom 06.10.2026 als Fixtures.
Abgedeckt: Schnittstellen-Parsing (MockTransport), Katalog-Vollständigkeit gegen Fixtures,
Stichwortsuche, Auswertungslogik je Modus, Checker mit Fake-Daten, Bot-Ablauf als
Smoke-Test. Manuelle Live-Prüfung: `python -m scrapers.etermin <schlüssel>`.
