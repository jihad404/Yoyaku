import asyncio
from datetime import date, datetime

import pytest

from conftest import FakeAvailability, FakeContext, callback_datas
from database.models import create_search, get_active_searches, get_search, load_state
from manager import checker
from manager.evaluate import initial_state
from scrapers.etermin import Slot

NOW = datetime(2026, 10, 6, 12, 0)
D = lambda day: date(2026, 10, day)  # noqa: E731


@pytest.fixture(autouse=True)
def reset_checker_state():
    checker._empty_streak.clear()
    checker._site_failures.clear()
    checker._site_alerted.clear()


def run(context, availability, now=NOW):
    asyncio.run(checker.check_and_notify(context, availability=availability, now=now))


def slot(day, hh, station="Hamborn"):
    return Slot(datetime(day.year, day.month, day.day, hh, 0), f"Bürger-Service-Station-{station}_Slot2")


def test_earliest_notifies_with_times_and_buttons(make_user):
    user = make_user(100)
    sid = create_search(user['id'], "wiederzulassung", "earliest",
                        state=initial_state("earliest", None, [D(14)], NOW))
    fake = FakeAvailability(days={"wiederzulassung": [D(9), D(14)]},
                            slots={("wiederzulassung", D(9)): [Slot(datetime(2026, 10, 9, 9, 20), "Fahrzeugzulassung Slot_1")]})
    ctx = FakeContext()
    run(ctx, fake)

    assert len(ctx.bot.sent) == 1
    chat_id, text, markup = ctx.bot.sent[0]
    assert chat_id == 100
    assert "Früherer Termin" in text and "Fr 09.10." in text and "09:20" in text and "Mi 14.10." in text
    assert f"stop:{sid}" in callback_datas(markup)
    assert "https://www.etermin.net/stadt-duisburg-zul?serviceid=217884" in callback_datas(markup)
    assert load_state(get_search(sid))["earliest"] == "2026-10-09"


def test_each_service_fetched_once_per_round(make_user):
    a, b = make_user(100), make_user(200)
    for u in (a, b):
        create_search(u['id'], "reisepass", "earliest", state=initial_state("earliest", None, [], NOW))
    create_search(a['id'], "fs_umtausch", "earliest", state=initial_state("earliest", None, [], NOW))
    fake = FakeAvailability(days={"reisepass": [D(20)]})
    ctx = FakeContext()
    run(ctx, fake)
    assert sorted(fake.day_calls) == ["fs_umtausch", "reisepass"]
    assert {c for c, _, _ in ctx.bot.sent} == {100, 200}


def test_location_filter(make_user):
    user = make_user(100)
    create_search(user['id'], "personalausweis", "earliest", location="hamborn",
                  state=initial_state("earliest", None, [D(20)], NOW))
    fake = FakeAvailability(
        days={"personalausweis": [D(9), D(14), D(20)]},
        slots={("personalausweis", D(9)): [slot(D(9), 9, "Mitte")],
               ("personalausweis", D(14)): [slot(D(14), 10, "Hamborn"), slot(D(14), 11, "Mitte")]},
    )
    ctx = FakeContext()
    run(ctx, fake)
    text = ctx.bot.sent[0][1]
    assert "Mi 14.10." in text and "10:00" in text
    assert "Fr 09.10." not in text and "11:00" not in text
    assert "Bürgerservice Hamborn" in text


def test_without_location_groups_times_by_station(make_user):
    user = make_user(100)
    create_search(user['id'], "personalausweis", "earliest", state=initial_state("earliest", None, [], NOW))
    fake = FakeAvailability(days={"personalausweis": [D(9)]},
                            slots={("personalausweis", D(9)): [slot(D(9), 9, "Mitte"), slot(D(9), 10, "Hamborn")]})
    ctx = FakeContext()
    run(ctx, fake)
    assert "Mitte 09:00 · Hamborn 10:00" in ctx.bot.sent[0][1]


def test_expired_until_search_ends(make_user):
    user = make_user(100)
    sid = create_search(user['id'], "reisepass", "until", target_date="2026-10-05",
                        state=initial_state("until", D(5), [], datetime(2026, 10, 1)))
    ctx = FakeContext()
    run(ctx, FakeAvailability())
    assert not get_search(sid)['is_active']
    assert "Suche beendet" in ctx.bot.sent[0][1]
    assert ctx.bot.sent[0][2] is None


def test_admin_alert_after_three_failed_rounds_and_recovery(make_user):
    user = make_user(100)
    create_search(user['id'], "reisepass", "earliest", state=initial_state("earliest", None, [], NOW))
    fake = FakeAvailability(fail={"reisepass"})
    ctx = FakeContext()
    for _ in range(4):
        run(ctx, fake)
    admin = [t for c, t, _ in ctx.bot.sent if c == 1]
    assert len(admin) == 1 and "Bürgerservice" in admin[0]

    fake.fail.clear()
    run(ctx, fake)
    admin = [t for c, t, _ in ctx.bot.sent if c == 1]
    assert len(admin) == 2 and "wieder" in admin[1]


def test_blocked_user_searches_are_deactivated(make_user):
    user = make_user(100)
    create_search(user['id'], "reisepass", "earliest", state=initial_state("earliest", None, [], NOW))
    create_search(user['id'], "fs_umtausch", "earliest", state=initial_state("earliest", None, [], NOW))
    ctx = FakeContext()
    ctx.bot.blocked.add(100)
    run(ctx, FakeAvailability(days={"reisepass": [D(9)], "fs_umtausch": [D(9)]}))
    assert get_active_searches(user['id']) == []


def test_empty_result_needs_two_rounds(make_user):
    user = make_user(100)
    create_search(user['id'], "reisepass", "day", target_date="2026-10-14",
                  state=initial_state("day", D(14), [D(14)], NOW))
    fake = FakeAvailability(days={"reisepass": []})
    ctx = FakeContext()
    run(ctx, fake)
    assert ctx.bot.sent == []
    run(ctx, fake)
    assert "nicht mehr verfügbar" in ctx.bot.sent[0][1]


def test_unknown_service_key_is_skipped(make_user):
    user = make_user(100)
    create_search(user['id'], "gibt_es_nicht", "earliest")
    ctx = FakeContext()
    run(ctx, FakeAvailability())
    assert ctx.bot.sent == []


def test_uninitialized_search_reports_current_state(make_user):
    user = make_user(100)
    create_search(user['id'], "reisepass", "until", target_date="2026-10-20", state={})
    ctx = FakeContext()
    run(ctx, FakeAvailability(days={"reisepass": [D(9), D(25)]}))
    text = ctx.bot.sent[0][1]
    assert "Neue Termine bis 20.10." in text and "Fr 09.10." in text and "25.10." not in text
