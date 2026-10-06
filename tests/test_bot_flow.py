import asyncio
from datetime import date, datetime, timedelta

import pytest

from conftest import FakeContext, FakeUpdate, callback_datas
from bot import handlers, search_flow, searches
from database.models import create_search, get_active_searches, get_search, load_state
from scrapers.etermin import Slot

TODAY = date.today()
IN = lambda n: TODAY + timedelta(days=n)  # noqa: E731


def run(coro):
    return asyncio.run(coro)


def click(handler, user_id, data, ctx):
    update = FakeUpdate(user_id, data=data)
    run(handler(update, ctx))
    return update.callback_query


def send(handler, user_id, text, ctx):
    update = FakeUpdate(user_id, text=text)
    run(handler(update, ctx))
    return update.message


@pytest.fixture
def user(make_user):
    return make_user(100)


@pytest.fixture
def ctx():
    return FakeContext()


# --- Navigation ----------------------------------------------------------------

def test_full_flow_with_location_and_earliest(user, ctx, fake_availability):
    fake_availability.days_by_key["personalausweis"] = [IN(2), IN(5)]
    fake_availability.slots_by[("personalausweis", IN(5))] = [
        Slot(datetime.combine(IN(5), datetime.min.time()).replace(hour=9), "Bürger-Service-Station-Hamborn")]

    msg = send(search_flow.search_command, 100, "/search", ctx)
    assert "nav:t:ausweis" in callback_datas(msg.replies[0][1])

    q = click(search_flow.on_navigation, 100, "nav:t:ausweis", ctx)
    assert "svc:personalausweis" in callback_datas(q.edits[0][1])
    assert "nav:home" in callback_datas(q.edits[0][1])

    q = click(search_flow.on_service, 100, "svc:personalausweis", ctx)
    assert {"loc:any", "loc:hamborn"} <= set(callback_datas(q.edits[0][1]))

    q = click(search_flow.on_location, 100, "loc:hamborn", ctx)
    assert "mode:earliest" in callback_datas(q.edits[0][1])

    q = click(search_flow.on_mode, 100, "mode:earliest", ctx)
    text, markup = q.edits[-1]
    assert "Suche gestartet" in text and "Bürgerservice Hamborn" in text and "09:00" in text

    [search] = get_active_searches(user['id'])
    assert (search['search_type'], search['mode'], search['location']) == ("personalausweis", "earliest", "hamborn")
    assert load_state(search)["earliest"] == IN(5).isoformat()   # IN(2) hat keinen Hamborn-Termin
    assert f"stop:{search['id']}" in callback_datas(markup)
    assert "draft" not in ctx.user_data


def test_subtopics_for_large_topics(user, ctx):
    q = click(search_flow.on_navigation, 100, "nav:t:fahrzeug", ctx)
    assert "nav:st:fahrzeug:kennzeichen" in callback_datas(q.edits[0][1])
    q = click(search_flow.on_navigation, 100, "nav:st:fahrzeug:kennzeichen", ctx)
    datas = callback_datas(q.edits[0][1])
    assert "svc:wunschkennzeichen" in datas and "nav:t:fahrzeug" in datas


def test_service_without_locations_skips_location_step(user, ctx):
    q = click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    assert "mode:earliest" in callback_datas(q.edits[0][1])


def test_until_quick_choice(user, ctx, fake_availability):
    fake_availability.days_by_key["wiederzulassung"] = [IN(3), IN(30)]
    click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    q = click(search_flow.on_mode, 100, "mode:until", ctx)
    assert "until:14" in callback_datas(q.edits[0][1])
    q = click(search_flow.on_until, 100, "until:14", ctx)
    [search] = get_active_searches(user['id'])
    assert search['mode'] == "until" and search['target_date'] == IN(14).isoformat()
    assert load_state(search)["known"] == [IN(3).isoformat()]


def test_day_mode_with_typed_date(user, ctx, fake_availability):
    click(search_flow.on_service, 100, "svc:reisepass", ctx)
    click(search_flow.on_location, 100, "loc:any", ctx)
    click(search_flow.on_mode, 100, "mode:day", ctx)
    assert ctx.user_data["awaiting"] == "day"

    msg = send(search_flow.on_text, 100, "kein datum", ctx)
    assert "TT.MM.JJJJ" in msg.replies[0][0]
    msg = send(search_flow.on_text, 100, (TODAY - timedelta(days=1)).strftime("%d.%m.%Y"), ctx)
    assert "Vergangenheit" in msg.replies[0][0]

    msg = send(search_flow.on_text, 100, IN(10).strftime("%d.%m.%Y"), ctx)
    assert msg.replies[0][0].startswith("⏳")
    assert "Suche gestartet" in msg.replies[-1][0]
    [search] = get_active_searches(user['id'])
    assert search['mode'] == "day" and search['target_date'] == IN(10).isoformat() and search['location'] is None


def test_keyword_search(user, ctx):
    msg = send(search_flow.on_text, 100, "reisepass", ctx)
    assert "svc:reisepass" in callback_datas(msg.replies[0][1])
    msg = send(search_flow.on_text, 100, "qwertz", ctx)
    assert "nichts gefunden" in msg.replies[0][0]
    assert "nav:t:ausweis" in callback_datas(msg.replies[0][1])


def test_limit_and_duplicate(user, ctx, fake_availability):
    click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    click(search_flow.on_mode, 100, "mode:earliest", ctx)
    click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    q = click(search_flow.on_mode, 100, "mode:earliest", ctx)
    assert "läuft bereits" in q.edits[-1][0]

    for key in ("reisepass", "fs_umtausch", "gewerbe_anmeldung", "fund_abholen"):
        create_search(user['id'], key, "earliest")
    msg = send(search_flow.search_command, 100, "/search", ctx)
    assert "bereits 5 aktive Suchen" in msg.replies[0][0]


def test_etermin_down_still_creates_search(user, ctx, fake_availability):
    fake_availability.fail.add("wiederzulassung")
    click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    q = click(search_flow.on_mode, 100, "mode:earliest", ctx)
    assert "nicht abrufen" in q.edits[-1][0]
    [search] = get_active_searches(user['id'])
    assert load_state(search) == {}


def test_stale_buttons(user, ctx):
    q = click(search_flow.on_service, 100, "svc:gibt_es_nicht", ctx)
    assert "abgelaufen" in q.edits[0][0]
    q = click(search_flow.on_mode, 100, "mode:earliest", ctx)   # kein Entwurf
    assert "abgelaufen" in q.edits[0][0]
    q = click(search_flow.on_navigation, 100, "nav:t:quatsch", ctx)
    assert "abgelaufen" in q.edits[0][0]


def test_double_click_creates_only_one_search(user, ctx, fake_availability):
    """Zwei gleichzeitige Klicks auf denselben Modus-Button (Updates laufen parallel)."""
    click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)

    async def both():
        await asyncio.gather(
            search_flow.on_mode(FakeUpdate(100, data="mode:earliest"), ctx),
            search_flow.on_mode(FakeUpdate(100, data="mode:earliest"), ctx),
        )
    run(both())
    assert len(get_active_searches(user['id'])) == 1


def test_too_old_query_does_not_abort_handler(user, ctx, monkeypatch):
    from conftest import FakeQuery
    from telegram.error import BadRequest

    async def too_old(self, text=None, show_alert=False):
        raise BadRequest("Query is too old and response timeout expired or query id is invalid")
    monkeypatch.setattr(FakeQuery, "answer", too_old)

    q = click(search_flow.on_service, 100, "svc:wiederzulassung", ctx)
    assert "mode:earliest" in callback_datas(q.edits[0][1])   # Handler lief trotzdem weiter
    q = click(search_flow.on_service, 100, "svc:gibt_es_nicht", ctx)
    assert "abgelaufen" in q.edits[0][0]


def test_unapproved_users_are_blocked(make_user, ctx):
    make_user(300, approved=False)
    msg = send(search_flow.search_command, 300, "/search", ctx)
    assert "nicht freigeschaltet" in msg.replies[0][0]
    msg = send(search_flow.on_text, 300, "reisepass", ctx)
    assert "geprüft" in msg.replies[0][0]
    msg = send(search_flow.on_text, 999, "reisepass", ctx)
    assert "registriere" in msg.replies[0][0]


# --- /status und /stop -------------------------------------------------------

def test_status_list_and_show(user, ctx, fake_availability):
    fake_availability.days_by_key["reisepass"] = [IN(4)]
    sid = create_search(user['id'], "reisepass", "until", target_date=IN(20).isoformat(), location="mitte")
    msg = send(searches.status_command, 100, "/status", ctx)
    assert f"show:{sid}" in callback_datas(msg.replies[0][1])
    assert "Reisepass beantragen · Mitte" in msg.replies[0][1].inline_keyboard[0][0].text

    q = click(searches.on_show, 100, f"show:{sid}", ctx)
    assert "Aktueller Stand" in q.edits[0][0]
    assert "keine freien Termine" in q.edits[0][0]  # IN(4) hat keinen Mitte-Termin


def test_stop_from_list_and_from_notification(user, ctx):
    a = create_search(user['id'], "reisepass", "earliest")
    b = create_search(user['id'], "fs_umtausch", "earliest")

    q = click(searches.on_stop, 100, f"stopl:{a}", ctx)
    assert not get_search(a)['is_active']
    assert f"stopl:{b}" in callback_datas(q.edits[0][1])

    q = click(searches.on_stop, 100, f"stop:{b}", ctx)
    assert not get_search(b)['is_active'] and q.markup_removed
    assert "Suche beendet" in q.message.replies[0][0]


def test_stop_all(user, ctx):
    create_search(user['id'], "reisepass", "earliest")
    create_search(user['id'], "fs_umtausch", "earliest")
    q = click(searches.on_stop_all, 100, "stopall", ctx)
    assert "2 Suche(n) beendet" in q.edits[0][0]
    assert get_active_searches(user['id']) == []


def test_cannot_touch_other_users_search(make_user, ctx):
    owner = make_user(100)
    make_user(200)
    sid = create_search(owner['id'], "reisepass", "earliest")
    click(searches.on_stop, 200, f"stopl:{sid}", ctx)
    q = click(searches.on_show, 200, f"show:{sid}", ctx)
    assert get_search(sid)['is_active']
    assert q.edits == []


def test_start_shows_new_help(user, ctx):
    msg = send(handlers.start, 100, "/start", ctx)
    assert "/search" in msg.replies[0][0] and "Stichwort" in msg.replies[0][0]
