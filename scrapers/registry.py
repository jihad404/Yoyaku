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
# Höchstens so viele gleichzeitige Anfragen an eTermin (schont den Server,
# ist aber deutlich schneller als strikt nacheinander)
MAX_PARALLEL = 4


class Availability:
    def __init__(self, client_factory=etermin.make_client, ttl: float = CACHE_TTL):
        self._client_factory = client_factory
        self._client = None
        self._ttl = ttl
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL)
        self._cache: dict = {}
        self._locks: dict = {}

    def _get_client(self):
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _cached(self, key, fetch):
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self._ttl:
                return hit[1]
            async with self._semaphore:
                value = await fetch()
            self._cache[key] = (time.monotonic(), value)
            return value

    async def days(self, service: Service) -> list[date]:
        """Alle Tage mit freien Terminen (alle Standorte)."""
        site = SITES[service.site]
        return await self._cached(
            ("days", site.webid, service.sid),
            lambda: etermin.available_days(self._get_client(), site.webid, service.sid),
        )

    async def slots(self, service: Service, day: date, location: str | None = None) -> list[etermin.Slot]:
        """Freie Zeitfenster eines Tages, optional nur an einem Standort."""
        site = SITES[service.site]
        result = await self._cached(
            ("slots", site.webid, service.sid, day),
            lambda: etermin.slots(self._get_client(), site.webid, service.sid, day),
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
