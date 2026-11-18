"""Täglicher Katalogabgleich: neue/verschwundene, nicht mehr buchbare und geänderte Dienstleistungen."""
import asyncio
import copy

import httpx
import pytest

from conftest import FakeContext, load_fixture
from database.models import create_search, get_search, load_state
from manager import catalog_sync
from scrapers import etermin
from scrapers.catalog import SITES

STVA = SITES["fahrerlaubnis"].webid


@pytest.fixture
def responses():
    """servicegroupservice-Antworten je Buchungsseite; Tests dürfen sie verändern."""
    return {site.webid: load_fixture(f"servicegroupservice_{site.webid}.json") for site in SITES.values()}


def _client(responses):
    def handler(request):
        return httpx.Response(200, json=responses[request.headers["webid"]])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=etermin.BASE_URL)


def compare(responses):
    async def run():
        async with _client(responses) as client:
            return await catalog_sync.compare_catalog(client)
    return asyncio.run(run())


def entry(responses, webid, sid):
    return next(e for e in responses[webid] if e.get("sid") == sid)


def test_current_etermin_data_matches_catalog(db, responses):
    # Die umgezogenen Führerschein-Dienstleistungen (MOVED) lösen keine Meldung aus
    lines, affected = compare(responses)
    assert lines == [] and affected == {}


def test_moved_services_would_be_detected_from_their_text(responses):
    ersterteilung = next(e for e in asyncio.run(_list(responses, STVA)) if e["sid"] == 110036)
    assert catalog_sync.booking_elsewhere(ersterteilung) == \
        "Dies kann ausschließlich im Bürgerservice Ihrer Wahl erledigt werden!"


async def _list(responses, webid):
    async with _client(responses) as client:
        return await etermin.list_services(client, webid)


def test_tip_for_alternative_office_is_not_a_problem(responses):
    # "Tipp: Dies können Sie auch im Bürgerservice … erledigen" → weiterhin buchbar
    verlaengerung_c = next(e for e in asyncio.run(_list(responses, STVA)) if e["sid"] == 110019)
    assert "auch im Bürgerservice" in verlaengerung_c["description"]
    assert catalog_sync.booking_elsewhere(verlaengerung_c) is None


def test_catalog_service_booked_elsewhere_is_reported(db, responses):
    ersatz = entry(responses, STVA, 110007)
    ersatz["sa"] = "Weitere Informationen<br><br>Dies kann ausschließlich im Bürgerservice erledigt werden!"
    ersatz["bt"] = 1

    lines, affected = compare(responses)

    assert affected == {"fs_ersatz": "Dies kann ausschließlich im Bürgerservice erledigt werden!"}
    assert any(line.startswith("🚫 Fahrerlaubnisbehörde: Ersatz nach Verlust / Diebstahl (ID 110007)")
               for line in lines)


def test_no_booking_flag_alone_is_reported(db, responses):
    entry(responses, STVA, 110007)["bt"] = 1
    _, affected = compare(responses)
    assert affected == {"fs_ersatz": catalog_sync.NO_BOOKING_TEXT}


def test_changes_are_reported_once(db, responses):
    assert compare(responses)[0] == []  # erster Abgleich legt nur den Stand an

    changed = copy.deepcopy(responses)
    entry(changed, STVA, 110007)["sa"] += "<br>Ab dem 01.12. nur nach Voranmeldung."
    entry(changed, STVA, 110027)["s"] = "Wechsel der Fahrschule"
    entry(changed, STVA, 110036)["bt"] = 0

    lines, affected = compare(changed)
    assert affected == {}
    assert sorted(lines) == sorted([
        "✏️ Fahrerlaubnisbehörde: Hinweistext zu „Ersatz nach  Verlust/Diebstahl“ (ID 110007) geändert: "
        "„Ab dem 01.12. nur nach Voranmeldung.“",
        "✏️ Fahrerlaubnisbehörde: „Fahrschulwechsel“ (ID 110027) heißt jetzt „Wechsel der Fahrschule“",
        "✏️ Fahrerlaubnisbehörde: „Ersterteilung“ (ID 110036) bietet wieder eine Terminwahl an",
    ])

    assert compare(changed)[0] == []  # derselbe Stand → keine erneute Meldung


def test_sync_informs_admin_and_affected_users_once(db, make_user, responses):
    user = make_user(100)
    sid = create_search(user['id'], "fs_ersatz", "earliest", state={"initialized": True})
    other = create_search(user['id'], "reisepass", "earliest", state={"initialized": True})
    entry(responses, STVA, 110007)["sa"] = "Dies kann ausschließlich im Bürgerservice erledigt werden!"

    ctx = FakeContext()
    for _ in range(2):
        asyncio.run(catalog_sync.sync_catalog(ctx, client_factory=lambda: _client(responses)))

    admin = [t for c, t, _ in ctx.bot.sent if c == 1]
    users = [t for c, t, _ in ctx.bot.sent if c == 100]
    assert len(admin) == 2 and "🚫" in admin[0] and "MOVED" in admin[0]
    assert len(users) == 1
    assert "nicht mehr gebucht werden" in users[0] and "ausschließlich im Bürgerservice" in users[0]
    assert load_state(get_search(sid))["gone_notified"] is True
    assert "gone_notified" not in load_state(get_search(other))


def test_sync_retries_user_notice_when_undelivered(db, make_user, responses):
    from telegram.error import NetworkError

    user = make_user(100)
    sid = create_search(user['id'], "fs_ersatz", "earliest", state={"initialized": True})
    entry(responses, STVA, 110007)["sa"] = "Dies kann ausschließlich im Bürgerservice erledigt werden!"
    ctx = FakeContext()
    ctx.bot.failures[100] = [NetworkError("weg")]

    asyncio.run(catalog_sync.sync_catalog(ctx, client_factory=lambda: _client(responses)))
    assert "gone_notified" not in load_state(get_search(sid))

    asyncio.run(catalog_sync.sync_catalog(ctx, client_factory=lambda: _client(responses)))
    assert [c for c, _, _ in ctx.bot.sent].count(100) == 1
    assert load_state(get_search(sid))["gone_notified"] is True
