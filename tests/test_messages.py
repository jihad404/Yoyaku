from datetime import date, datetime

from manager.evaluate import Decision
from manager.messages import format_slots, mode_label, notification_text
from scrapers.catalog import SERVICES
from scrapers.etermin import Slot


def _slot(hh, mm, calendar="Fahrzeugzulassung Slot_1"):
    return Slot(datetime(2026, 10, 14, hh, mm), calendar)


def test_duplicate_times_shown_once():
    slots = [_slot(7, 30), _slot(7, 30), _slot(7, 30), _slot(7, 45)]
    assert format_slots(SERVICES["wiederzulassung"], None, slots) == "07:30, 07:45"


def test_more_than_three_times_are_summarized():
    slots = [_slot(8, m) for m in (0, 15, 30, 45)] + [_slot(9, 0)]
    assert format_slots(SERVICES["wiederzulassung"], None, slots) == "08:00, 08:15, 08:30 (+2 weitere)"


def test_mode_labels():
    assert mode_label("earliest", None) == "so früh wie möglich"
    assert mode_label("until", date(2026, 10, 20)) == "bis spätestens 20.10.2026"
    assert mode_label("day", date(2026, 10, 20)) == "am 20.10.2026"


def test_first_notification_without_previous():
    d = Decision("earlier", {}, [date(2026, 10, 14)], previous=None)
    text = notification_text(SERVICES["reisepass"], "mitte", d, None, {})
    assert text.startswith("🔔 Termin frei!")
    assert "Reisepass beantragen · Bürgerservice Mitte" in text
    assert "Mi 14.10." in text and "vorher" not in text
