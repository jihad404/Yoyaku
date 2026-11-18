import asyncio
from datetime import date, datetime

import pytest

from scrapers import etermin, registry
from scrapers.catalog import SERVICES

D = lambda day: date(2026, 10, day)  # noqa: E731


@pytest.fixture(autouse=True)
def no_settings_requests(monkeypatch):
    async def settings(client, webid):
        return {}

    async def services(client, webid):
        return []
    monkeypatch.setattr(etermin, "booking_settings", settings)
    monkeypatch.setattr(etermin, "list_services", services)


class SlowSlots:
    """Ersetzt etermin.slots: jede Anfrage dauert 50 ms, misst die Parallelität."""

    def __init__(self, hamborn_days):
        self.hamborn_days = set(hamborn_days)
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = []

    async def __call__(self, client, webid, sid, day, params=None):
        self.calls.append(day)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.05)
        self.in_flight -= 1
        station = "Hamborn" if day in self.hamborn_days else "Mitte"
        return [etermin.Slot(datetime(day.year, day.month, day.day, 9), f"Bürger-Service-Station-{station}")]


def test_matching_days_fetches_in_parallel_and_keeps_order(monkeypatch):
    fake = SlowSlots(hamborn_days=[D(20), D(8), D(25)])
    monkeypatch.setattr(etermin, "slots", fake)
    days = [D(d) for d in range(1, 31)]

    async def run():
        availability = registry.Availability(client_factory=lambda: None)
        return await availability.matching_days(SERVICES["personalausweis"], "hamborn", days, limit=2)

    result = asyncio.run(run())
    assert result == [D(8), D(20)]                       # Reihenfolge nach Datum, Limit eingehalten
    assert 1 < fake.max_in_flight <= registry.MAX_PARALLEL
    assert len(fake.calls) < len(days)                   # bricht nach Erreichen des Limits ab


def test_requests_use_booking_page_settings_and_service_duration(monkeypatch):
    calls = {"settings": 0, "services": 0}
    seen_params, seen_months = [], []

    async def fake_settings(client, webid):
        calls["settings"] += 1
        return {"caching": "true", "appfuture": "30"}

    async def fake_services(client, webid):
        calls["services"] += 1
        return [{"sid": 90492, "name": "Anmeldungen", "group": "x", "duration": 12}]

    async def fake_days(client, webid, sid, months=None, params=None):
        seen_params.append(params)
        seen_months.append(months)
        return [D(15)]

    async def fake_slots(client, webid, sid, day, params=None):
        seen_params.append(params)
        return []

    monkeypatch.setattr(etermin, "booking_settings", fake_settings)
    monkeypatch.setattr(etermin, "list_services", fake_services)
    monkeypatch.setattr(etermin, "available_days", fake_days)
    monkeypatch.setattr(etermin, "slots", fake_slots)

    async def run():
        availability = registry.Availability(client_factory=lambda: None)
        await availability.days(SERVICES["anmeldung"])
        await availability.slots(SERVICES["anmeldung"], D(15))
        await availability.slots(SERVICES["anmeldung"], D(16))

    asyncio.run(run())
    assert all(p == {"caching": "true", "appfuture": "30", "duration": "12"} for p in seen_params)
    assert calls == {"settings": 1, "services": 1}   # Einstellungen werden zwischengespeichert
    assert seen_months == [etermin.months_ahead(date.today(), "30")]   # Monate aus dem Buchungszeitraum


def test_prune_drops_expired_entries_and_unused_locks(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(registry.time, "monotonic", lambda: clock[0])

    async def fetch_value():
        return "wert"

    async def run():
        availability = registry.Availability(client_factory=lambda: None)
        await availability._cached("kurz", fetch_value, ttl=60)
        await availability._cached("lang", fetch_value, ttl=6 * 60 * 60)
        clock[0] += registry.PRUNE_INTERVAL + 1      # "kurz" ist abgelaufen, Aufräumen fällig
        await availability._cached("neu", fetch_value, ttl=60)
        return availability

    availability = asyncio.run(run())
    assert set(availability._cache) == {"lang", "neu"}
    assert set(availability._locks) == {"lang", "neu"}


def test_matching_days_without_location_needs_no_requests(monkeypatch):
    fake = SlowSlots(hamborn_days=[])
    monkeypatch.setattr(etermin, "slots", fake)

    async def run():
        availability = registry.Availability(client_factory=lambda: None)
        return await availability.matching_days(SERVICES["personalausweis"], None, [D(1), D(2), D(3)], limit=2)

    assert asyncio.run(run()) == [D(1), D(2)]
    assert fake.calls == []
