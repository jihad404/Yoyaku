"""Client für die (inoffizielle) JSON-Schnittstelle von etermin.net.

Die Buchungsseiten der Stadt Duisburg laden ihre Daten über diese Schnittstelle;
jede Anfrage braucht den Header ``webid`` mit dem Namen der Buchungsseite.
"""
import asyncio
from dataclasses import dataclass
from datetime import date, datetime

import httpx

BASE_URL = "https://www.etermin.net"
USER_AGENT = "Yoyaku-Terminbot/1.0 (privater Telegram-Benachrichtigungsdienst)"
TIMEOUT = 15

# Parameter, die auch die Buchungsseite selbst mitschickt
_TIMESLOT_PARAMS = {
    "capacity": "1",
    "caching": "false",
    "duration": "0",
    "cluster": "false",
    "slottype": "0",
    "fillcalendarstrategy": "0",
    "showavcap": "false",
    "appfuture": "70",
    "appdeadline": "0",
    "msdcm": "0",
    "tzaccount": "Europe/Berlin",
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
        timeout=TIMEOUT,
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


def _month_starts(today: date, months: int) -> list[date]:
    starts = [today]
    year, month = today.year, today.month
    for _ in range(months - 1):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        starts.append(date(year, month, 1))
    return starts


async def available_days(client: httpx.AsyncClient, webid: str, service_id: int,
                         today: date | None = None, months: int = 3) -> list[date]:
    """Tage mit freien Terminen, sortiert. Eine Anfrage pro Monat
    (``rangesearch`` liefert jeweils vom Startdatum bis Monatsende)."""
    today = today or date.today()
    days: set[date] = set()
    responses = await asyncio.gather(*(
        _get_list(client, webid, "/api/timeslots",
                  {"date": start.isoformat(), "serviceid": str(service_id), "rangesearch": "1", **_TIMESLOT_PARAMS})
        for start in _month_starts(today, months)
    ))
    for response in responses:
        for entry in response:
            try:
                days.add(datetime.fromisoformat(entry["start"]).date())
            except (KeyError, TypeError, ValueError) as e:
                raise EterminError(f"{webid} timeslots: unerwarteter Eintrag {entry!r}") from e
    return sorted(days)


async def slots(client: httpx.AsyncClient, webid: str, service_id: int, day: date) -> list[Slot]:
    """Einzelne freie Zeitfenster eines Tages, sortiert nach Uhrzeit."""
    params = {"date": day.isoformat(), "serviceid": str(service_id), **_TIMESLOT_PARAMS}
    result = []
    for entry in await _get_list(client, webid, "/api/timeslots", params):
        try:
            result.append(Slot(datetime.fromisoformat(entry["start"]), str(entry.get("calendarname") or "")))
        except (KeyError, TypeError, ValueError) as e:
            raise EterminError(f"{webid} timeslots: unerwarteter Eintrag {entry!r}") from e
    return sorted(result, key=lambda s: s.start)


async def list_services(client: httpx.AsyncClient, webid: str) -> list[dict]:
    """Alle buchbaren Dienstleistungen einer Buchungsseite."""
    services = []
    for entry in await _get_list(client, webid, "/api/servicegroupservice"):
        if not isinstance(entry, dict):
            raise EterminError(f"{webid} servicegroupservice: unerwarteter Eintrag {entry!r}")
        if entry.get("sid"):  # leere Gruppen haben keine sid
            services.append({"sid": int(entry["sid"]), "name": str(entry.get("s") or "").strip(),
                             "group": str(entry.get("sg") or "").strip()})
    return services


# ---------------------------------------------------------------------------
# Manuelle Live-Prüfung: python -m scrapers.etermin <katalog-schlüssel>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    from scrapers.catalog import SERVICES, SITES

    async def _main(key: str):
        service = SERVICES[key]
        site = SITES[service.site]
        async with make_client() as client:
            days = await available_days(client, site.webid, service.sid)
            print(f"{service.name} ({site.name}): {len(days)} Tage mit freien Terminen")
            for d in days[:5]:
                times = await slots(client, site.webid, service.sid, d)
                print(f"  {d:%a %d.%m.}  " + ", ".join(f"{s.start:%H:%M} {s.calendar}" for s in times[:4]))

    if len(sys.argv) != 2 or sys.argv[1] not in SERVICES:
        print("Aufruf: python -m scrapers.etermin <schlüssel>\nSchlüssel:", ", ".join(sorted(SERVICES)))
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
