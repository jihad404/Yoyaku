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


def test_booking_settings_mirror_the_booking_page():
    def handler(request):
        assert request.url.path == "/api/settingbs"
        return httpx.Response(200, json=load_fixture("settingbs_stadt-duisburg.json"))

    async def run():
        async with _client(handler) as client:
            return await etermin.booking_settings(client, "stadt-duisburg")

    params = asyncio.run(run())
    # genau die Werte, die die Buchungsseite am 06.10.2026 mitgeschickt hat
    assert params["caching"] == "true"
    assert params["appfuture"] == "30"
    assert params["appdeadline"] == "0"
    assert params["tzaccount"] == "W. Europe Standard Time"


def test_params_are_sent_with_requests():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[])

    params = {"caching": "true", "duration": "12", "appfuture": "30"}

    async def run():
        async with _client(handler) as client:
            await etermin.available_days(client, "stadt-duisburg", 90492, today=date(2026, 10, 6), months=1,
                                         params=params)
            await etermin.slots(client, "stadt-duisburg", 90492, date(2026, 10, 15), params=params)

    asyncio.run(run())
    for p in seen:
        assert (p["caching"], p["duration"], p["appfuture"]) == ("true", "12", "30")


def test_list_services_includes_duration():
    def handler(request):
        return httpx.Response(200, json=load_fixture("servicegroupservice_stadt-duisburg.json"))

    async def run():
        async with _client(handler) as client:
            return await etermin.list_services(client, "stadt-duisburg")

    anmeldung = next(s for s in asyncio.run(run()) if s["sid"] == 90492)
    assert anmeldung["duration"] == 12


def test_list_services_reads_hint_text_and_booking_flag():
    # Echte Antwort der Fahrerlaubnisbehörde vom 18.11.2026
    def handler(request):
        return httpx.Response(200, json=load_fixture("servicegroupservice_qterminstadtduisburgstva.json"))

    async def run():
        async with _client(handler) as client:
            return await etermin.list_services(client, "qterminstadtduisburgstva")

    services = {s["sid"]: s for s in asyncio.run(run())}
    ersterteilung, ersatz = services[110036], services[110007]
    assert ersterteilung["no_booking"] is True and ersatz["no_booking"] is False
    assert "Dies kann ausschließlich im Bürgerservice Ihrer Wahl erledigt werden!" in ersterteilung["description"]
    assert ersterteilung["description"].splitlines() == [
        "Dies kann ausschließlich im Bürgerservice Ihrer Wahl erledigt werden!",
        "Weitere Informationen",
        "Dies kann ausschließlich im Bürgerservice Ihrer Wahl erledigt werden! "
        "Hier geht es direkt zur Terminvereinbarung",
    ]
    assert [s["sid"] for s in services.values() if s["no_booking"]] == [110036, 110037, 110038, 110039]


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
    wiederzulassung = next(s for s in services if s["sid"] == 217884)
    assert wiederzulassung["name"] == "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs"
    assert wiederzulassung["group"] == "Fahrzeugzulassung"


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
