import asyncio
from datetime import date, datetime

import httpx
import pytest

from conftest import load_fixture
from scrapers import etermin


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=etermin.BASE_URL)


def test_available_days_queries_each_month_and_merges():
    calls = []

    def handler(request):
        calls.append((request.headers["webid"], dict(request.url.params)))
        start = request.url.params["date"]
        if start.startswith("2026-10"):
            return httpx.Response(200, json=load_fixture("timeslots_range_bs.json"))
        if start.startswith("2026-11"):
            return httpx.Response(200, json=[{"start": "2026-11-03T00:00:00"}, {"start": "2026-10-30T00:00:00"}])
        return httpx.Response(200, json=[])

    async def run():
        async with _client(handler) as client:
            return await etermin.available_days(client, "stadt-duisburg", 90152, today=date(2026, 10, 6), months=3)

    days = asyncio.run(run())

    assert [c[1]["date"] for c in calls] == ["2026-10-06", "2026-11-01", "2026-12-01"]
    assert all(c[0] == "stadt-duisburg" and c[1]["rangesearch"] == "1" and c[1]["serviceid"] == "90152" for c in calls)
    assert days[0] == date(2026, 10, 6)
    assert days[-1] == date(2026, 11, 3)
    assert days == sorted(set(days)), "sortiert und ohne Duplikate"
    assert len(days) == 13


def test_slots_parses_time_and_calendar():
    def handler(request):
        assert "rangesearch" not in request.url.params
        assert request.url.params["date"] == "2026-10-14"
        return httpx.Response(200, json=load_fixture("timeslots_day_bs.json"))

    async def run():
        async with _client(handler) as client:
            return await etermin.slots(client, "stadt-duisburg", 90152, date(2026, 10, 14))

    result = asyncio.run(run())
    assert result[0].start == datetime(2026, 10, 14, 8, 20)
    assert result[0].calendar == "Bürger-Service-Station-Meiderich/Beeck"
    assert result == sorted(result, key=lambda s: s.start)


def test_list_services_skips_empty_groups():
    def handler(request):
        return httpx.Response(200, json=load_fixture("servicegroupservice_stadt-duisburg-zul.json"))

    async def run():
        async with _client(handler) as client:
            return await etermin.list_services(client, "stadt-duisburg-zul")

    services = asyncio.run(run())
    assert len(services) == 34
    assert {"sid": 217884, "name": "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs",
            "group": "Fahrzeugzulassung"} in services


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="boom"),
    httpx.Response(200, text="<html>kein json</html>"),
    httpx.Response(200, json={"unerwartet": True}),
    httpx.Response(200, json=[{"ohne_start": 1}]),
])
def test_errors_raise_etermin_error(response):
    async def run():
        async with _client(lambda request: response) as client:
            await etermin.available_days(client, "stadt-duisburg", 1, today=date(2026, 10, 6), months=1)

    with pytest.raises(etermin.EterminError):
        asyncio.run(run())


def test_network_error_raises_etermin_error():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    async def run():
        async with _client(handler) as client:
            await etermin.slots(client, "stadt-duisburg", 1, date(2026, 10, 6))

    with pytest.raises(etermin.EterminError):
        asyncio.run(run())
