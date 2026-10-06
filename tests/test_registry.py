import asyncio
from datetime import date, datetime

from scrapers import etermin, registry
from scrapers.catalog import SERVICES

D = lambda day: date(2026, 10, day)  # noqa: E731


class SlowSlots:
    """Ersetzt etermin.slots: jede Anfrage dauert 50 ms, misst die Parallelität."""

    def __init__(self, hamborn_days):
        self.hamborn_days = set(hamborn_days)
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = []

    async def __call__(self, client, webid, sid, day):
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


def test_matching_days_without_location_needs_no_requests(monkeypatch):
    fake = SlowSlots(hamborn_days=[])
    monkeypatch.setattr(etermin, "slots", fake)

    async def run():
        availability = registry.Availability(client_factory=lambda: None)
        return await availability.matching_days(SERVICES["personalausweis"], None, [D(1), D(2), D(3)], limit=2)

    assert asyncio.run(run()) == [D(1), D(2)]
    assert fake.calls == []
