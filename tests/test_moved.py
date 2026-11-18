"""Umgezogene Dienstleistungen: Umstellung aktiver Suchen beim Start und einmalige Nachricht."""
import asyncio
from datetime import date, datetime

from conftest import FakeAvailability, FakeContext, callback_datas
from database.models import create_search, deactivate_search, get_active_searches, get_search, load_state
from manager import checker
from scrapers.catalog import MOVED, SERVICES

NOW = datetime(2026, 11, 18, 12, 0)


def test_init_db_moves_active_searches(db, make_user):
    user = make_user(100)
    active = create_search(user['id'], "fs_ersterteilung", "until", "2026-12-31", state={"initialized": True})
    stopped = create_search(user['id'], "fs_bf17", "earliest")
    deactivate_search(stopped)

    db.init_db()  # Start des Bots

    moved = get_search(active)
    assert moved['search_type'] == "bs_fs_antrag"
    assert (moved['mode'], moved['target_date'], moved['location']) == ("until", "2026-12-31", None)
    assert load_state(moved) == {"moved_from": "fs_ersterteilung"}
    assert get_search(stopped)['search_type'] == "fs_bf17", "beendete Suchen bleiben unverändert"


def test_init_db_keeps_only_one_of_identical_searches(db, make_user):
    user = make_user(100)
    first = create_search(user['id'], "fs_ersterteilung", "earliest")
    create_search(user['id'], "fs_erweiterung", "earliest")
    third = create_search(user['id'], "fs_neuerteilung", "day", "2026-12-01")

    db.init_db()

    remaining = get_active_searches(user['id'])
    assert [(s['id'], s['search_type'], s['mode']) for s in remaining] == [
        (first, "bs_fs_antrag", "earliest"),
        (third, "bs_fs_antrag", "day"),
    ]


def test_checker_explains_move_once_then_reports_as_usual(db, make_user):
    user = make_user(100)
    create_search(user['id'], "fs_bf17", "earliest")
    db.init_db()
    fake = FakeAvailability(days={"bs_fs_antrag": [date(2026, 11, 19)]})
    ctx = FakeContext()

    for _ in range(2):
        asyncio.run(checker.check_and_notify(ctx, availability=fake, now=NOW))

    texts = [t for _, t, _ in ctx.bot.sent]
    assert len(texts) == 2
    assert "umgestellt" in texts[0] and "Begleitetes Fahren ab 17" in texts[0]
    assert "Fahrerlaubnisbehörde" in texts[0] and "Führerschein beantragen (alle Anträge) · Bürgerservice" in texts[0]
    assert "https://www.etermin.net/stadt-duisburg/serviceid/90496" in callback_datas(ctx.bot.sent[0][2])
    assert "Termin frei" in texts[1] and "Do 19.11." in texts[1]


def test_moved_entries_point_to_existing_services():
    for moved in MOVED.values():
        assert moved.old_key not in SERVICES
        assert moved.new_key in SERVICES
