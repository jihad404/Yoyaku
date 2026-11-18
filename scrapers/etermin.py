"""Client für die (inoffizielle) JSON-Schnittstelle von etermin.net.

Die Buchungsseiten der Stadt Duisburg laden ihre Daten über diese Schnittstelle;
jede Anfrage braucht den Header ``webid`` mit dem Namen der Buchungsseite.
"""
import asyncio
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

BASE_URL = "https://www.etermin.net"
USER_AGENT = "Yoyaku-Terminbot/1.0 (privater Telegram-Benachrichtigungsdienst)"
TIMEOUT = 15
# Höchstens so viele gleichzeitige HTTP-Anfragen an eTermin (weitere warten auf
# eine freie Verbindung). Schont den Server, ist aber schneller als nacheinander.
MAX_CONNECTIONS = 4
# Monatsabfragen, wenn die Buchungsseite keinen Buchungszeitraum angibt
DEFAULT_MONTHS = 3
MAX_MONTHS = 12

# Grundwerte der Parameter, die auch die Buchungsseite mitschickt. Die
# seitenspezifischen Werte (caching, Vorlauf, Zeitraum, Zeitzone) und die Dauer
# der Dienstleistung kommen aus booking_settings() bzw. list_services().
# Wichtig: Mit caching=false liefert eTermin bei manchen Seiten Zeiten, die
# online gar nicht buchbar sind (festgestellt am 06.10.2026 beim Bürgerservice).
_DEFAULT_PARAMS = {
    "capacity": "1",
    "caching": "true",
    "duration": "0",
    "cluster": "false",
    "slottype": "0",
    "fillcalendarstrategy": "0",
    "showavcap": "false",
    "appfuture": "30",
    "appdeadline": "0",
    "appdeadlinewm": "0",
    "msdcm": "0",
    "oneoff": "null",
    "calendarid": "",
    "tzaccount": "W. Europe Standard Time",
}

# Einstellung der Buchungsseite → Name des Anfrageparameters
_SETTING_PARAMS = {
    "caching": "caching",
    "cluster": "cluster",
    "fillcalendarstrategy": "fillcalendarstrategy",
    "showavcap": "showavcap",
    "appfuture": "appfuture",
    "appdeadline": "appdeadline",
    "appdeadlinewm": "appdeadlinewm",
    "msdcm": "msdcm",
    "timezone": "tzaccount",
}


class EterminError(Exception):
    """Schnittstelle nicht erreichbar oder Antwort im unerwarteten Format."""


@dataclass(frozen=True)
class Slot:
    start: datetime
    calendar: str


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        # pool=None: Anfragen dürfen beliebig lange auf eine freie Verbindung warten,
        # die 15 s gelten erst ab dem Senden
        timeout=httpx.Timeout(TIMEOUT, pool=None),
        limits=httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_CONNECTIONS),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


async def _get_list(client: httpx.AsyncClient, webid: str, path: str, params: dict | None = None) -> list:
    try:
        response = await client.get(path, params=params, headers={"webid": webid})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise EterminError(f"{webid} {path}: {e!r}") from e
    if not isinstance(data, list):
        raise EterminError(f"{webid} {path}: Liste erwartet, bekommen {type(data).__name__}")
    return data


def _param_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def booking_settings(client: httpx.AsyncClient, webid: str) -> dict:
    """Die Einstellungen der Buchungsseite als Anfrageparameter, so wie die
    Seite sie selbst an /api/timeslots schickt."""
    data = await _get_list(client, webid, "/api/settingbs", {"t": ""})
    if not data or not isinstance(data[0], dict):
        raise EterminError(f"{webid} settingbs: unerwartete Antwort")
    settings = data[0]
    return {param: _param_value(settings[key]) for key, param in _SETTING_PARAMS.items() if key in settings}


def _month_starts(today: date, months: int) -> list[date]:
    starts = [today]
    year, month = today.year, today.month
    for _ in range(months - 1):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        starts.append(date(year, month, 1))
    return starts


def months_ahead(today: date, appfuture) -> int:
    """Wie viele Monatsabfragen den Buchungszeitraum abdecken. ``appfuture`` ist
    die Einstellung der Buchungsseite in Kalendertagen (live geprüft am
    18.11.2026: letzter freier Tag = heute + appfuture)."""
    try:
        days = int(appfuture)
    except (TypeError, ValueError):
        return DEFAULT_MONTHS
    if days <= 0:
        return DEFAULT_MONTHS
    last = today + timedelta(days=days)
    return min((last.year - today.year) * 12 + last.month - today.month + 1, MAX_MONTHS)


async def available_days(client: httpx.AsyncClient, webid: str, service_id: int,
                         today: date | None = None, months: int = DEFAULT_MONTHS,
                         params: dict | None = None) -> list[date]:
    """Tage mit freien Terminen, sortiert. Eine Anfrage pro Monat
    (``rangesearch`` liefert jeweils vom Startdatum bis Monatsende)."""
    today = today or date.today()
    days: set[date] = set()
    base = {**_DEFAULT_PARAMS, **(params or {})}
    responses = await asyncio.gather(*(
        _get_list(client, webid, "/api/timeslots",
                  {"date": start.isoformat(), "serviceid": str(service_id), "rangesearch": "1", **base})
        for start in _month_starts(today, months)
    ))
    for response in responses:
        for entry in response:
            try:
                days.add(datetime.fromisoformat(entry["start"]).date())
            except (KeyError, TypeError, ValueError) as e:
                raise EterminError(f"{webid} timeslots: unerwarteter Eintrag {entry!r}") from e
    return sorted(days)


async def slots(client: httpx.AsyncClient, webid: str, service_id: int, day: date,
                params: dict | None = None) -> list[Slot]:
    """Einzelne freie Zeitfenster eines Tages, sortiert nach Uhrzeit."""
    query = {"date": day.isoformat(), "serviceid": str(service_id), **_DEFAULT_PARAMS, **(params or {})}
    result = []
    for entry in await _get_list(client, webid, "/api/timeslots", query):
        try:
            result.append(Slot(datetime.fromisoformat(entry["start"]), str(entry.get("calendarname") or "")))
        except (KeyError, TypeError, ValueError) as e:
            raise EterminError(f"{webid} timeslots: unerwarteter Eintrag {entry!r}") from e
    return sorted(result, key=lambda s: s.start)


def plain_text(text) -> str:
    """HTML-Beschreibung von eTermin als einfacher Text; Zeilenumbrüche und
    Absätze bleiben als einzelne Zeilen erhalten."""
    text = re.sub(r"<br\s*/?>|</(?:p|div|li|a)>", "\n", str(text or ""), flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


async def list_services(client: httpx.AsyncClient, webid: str) -> list[dict]:
    """Alle Dienstleistungen einer Buchungsseite.

    ``description`` ist der Hinweistext, den die Buchungsseite über der
    Terminwahl zeigt (Gruppe + Dienstleistung). ``no_booking`` entspricht dem
    eTermin-Feld ``bt``: Am 18.11.2026 stand es genau bei den Dienstleistungen
    auf 1, für die die Seite keine Terminwahl mehr anbot ("ausschließlich im
    Bürgerservice"), überall sonst auf 0.
    """
    services = []
    for entry in await _get_list(client, webid, "/api/servicegroupservice"):
        if not isinstance(entry, dict):
            raise EterminError(f"{webid} servicegroupservice: unerwarteter Eintrag {entry!r}")
        if entry.get("sid"):  # leere Gruppen haben keine sid
            description = "\n".join(t for t in (plain_text(entry.get("sga")), plain_text(entry.get("sa"))) if t)
            services.append({"sid": int(entry["sid"]), "name": str(entry.get("s") or "").strip(),
                             "group": str(entry.get("sg") or "").strip(),
                             "duration": int(entry.get("duration") or 0),
                             "description": description,
                             "no_booking": bool(entry.get("bt"))})
    return services


# ---------------------------------------------------------------------------
# Manuelle Live-Prüfung: python -m scrapers.etermin <katalog-schlüssel>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    from scrapers.catalog import SERVICES, SITES, booking_url
    from scrapers.registry import Availability

    async def _main(key: str):
        # über die Registry, damit genau dieselben Parameter wie im Bot verwendet werden
        service = SERVICES[key]
        availability = Availability()
        try:
            days = await availability.days(service)
            print(f"{service.name} ({SITES[service.site].name}): {len(days)} Tage mit freien Terminen")
            print(f"Buchungslink: {booking_url(service)}")
            for d in days[:5]:
                times = await availability.slots(service, d)
                print(f"  {d:%a %d.%m.}  " + ", ".join(f"{s.start:%H:%M} {s.calendar}" for s in times[:4]))
        finally:
            await availability.close()

    if len(sys.argv) != 2 or sys.argv[1] not in SERVICES:
        print("Aufruf: python -m scrapers.etermin <schlüssel>\nSchlüssel:", ", ".join(sorted(SERVICES)))
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
