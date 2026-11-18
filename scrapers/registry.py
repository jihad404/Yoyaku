"""Zentraler Zugriff auf freie Termine, mit kurzem Zwischenspeicher.

Bot und Checker fragen nur hierüber ab. Gleiche Anfragen innerhalb von
CACHE_TTL Sekunden werden aus dem Speicher beantwortet, parallele gleiche
Anfragen warten aufeinander statt eTermin doppelt zu belasten.
"""
import asyncio
import time
from datetime import date

from scrapers import etermin
from scrapers.catalog import SITES, Service, location_for_calendar

CACHE_TTL = 60
# Einstellungen der Buchungsseiten und Dauer der Dienstleistungen ändern sich selten
SETTINGS_TTL = 6 * 60 * 60
# Gleichzeitige Abfragen; die harte Grenze für HTTP-Anfragen setzt der Client
# (etermin.MAX_CONNECTIONS), hier wird nur entsprechend in Blöcken gearbeitet
MAX_PARALLEL = etermin.MAX_CONNECTIONS
# So oft werden abgelaufene Einträge aus dem Zwischenspeicher entfernt; ohne das
# wächst er bei monatelangem Betrieb mit jedem neuen Tag weiter
PRUNE_INTERVAL = 10 * 60


class Availability:
    def __init__(self, client_factory=etermin.make_client, ttl: float = CACHE_TTL):
        self._client_factory = client_factory
        self._client = None
        self._ttl = ttl
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL)
        self._cache: dict = {}   # key → (Zeitpunkt, Wert, Gültigkeit in s)
        self._locks: dict = {}
        self._last_prune = time.monotonic()

    def _get_client(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _cached(self, key, fetch, ttl: float | None = None):
        ttl = self._ttl if ttl is None else ttl
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            async with self._semaphore:
                value = await fetch()
            self._cache[key] = (time.monotonic(), value, ttl)
        self.prune()
        return value

    def prune(self, force: bool = False) -> None:
        """Entfernt abgelaufene Einträge und nicht benutzte Sperren (höchstens alle PRUNE_INTERVAL s)."""
        now = time.monotonic()
        if not force and now - self._last_prune < PRUNE_INTERVAL:
            return
        self._last_prune = now
        for key, (stored, _, ttl) in list(self._cache.items()):
            if now - stored >= ttl:
                del self._cache[key]
        for key, lock in list(self._locks.items()):
            if key not in self._cache and not lock.locked():
                del self._locks[key]

    async def _params(self, service: Service) -> dict:
        """Anfrageparameter wie auf der Buchungsseite: deren Einstellungen plus
        die Dauer der Dienstleistung."""
        webid = SITES[service.site].webid
        settings = await self._cached(
            ("settings", webid), lambda: etermin.booking_settings(self._get_client(), webid), SETTINGS_TTL)
        durations = await self._cached(
            ("durations", webid),
            lambda: self._durations(webid), SETTINGS_TTL)
        return {**settings, "duration": str(durations.get(service.sid, 0))}

    async def _durations(self, webid: str) -> dict:
        return {s["sid"]: s["duration"] for s in await etermin.list_services(self._get_client(), webid)}

    async def days(self, service: Service) -> list[date]:
        """Alle Tage mit freien Terminen (alle Standorte)."""
        site = SITES[service.site]
        params = await self._params(service)
        # nur so viele Monate abfragen, wie die Seite im Voraus buchbar macht
        months = etermin.months_ahead(date.today(), params.get("appfuture"))
        return await self._cached(
            ("days", site.webid, service.sid),
            lambda: etermin.available_days(self._get_client(), site.webid, service.sid, months=months,
                                           params=params),
        )

    async def slots(self, service: Service, day: date, location: str | None = None) -> list[etermin.Slot]:
        """Freie Zeitfenster eines Tages, optional nur an einem Standort."""
        site = SITES[service.site]
        params = await self._params(service)
        result = await self._cached(
            ("slots", site.webid, service.sid, day),
            lambda: etermin.slots(self._get_client(), site.webid, service.sid, day, params=params),
        )
        if location:
            result = [s for s in result if location_for_calendar(s.calendar) == location]
        return result

    async def matching_days(self, service: Service, location: str | None, days: list[date],
                            limit: int | None = None) -> list[date]:
        """Filtert Tage auf den Standort. Ohne Standort unverändert.
        Mit ``limit`` wird nach so vielen Treffern aufgehört (spart Anfragen)."""
        if not location:
            return days[:limit] if limit else days
        result = []
        # In Blöcken parallel abfragen; nach jedem Block prüfen, ob das Limit erreicht ist
        for i in range(0, len(days), MAX_PARALLEL):
            block = days[i:i + MAX_PARALLEL]
            found = await asyncio.gather(*(self.slots(service, day, location) for day in block))
            result += [day for day, slots in zip(block, found) if slots]
            if limit and len(result) >= limit:
                return result[:limit]
        return result


availability = Availability()
