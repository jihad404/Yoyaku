import pytest

from conftest import load_fixture
from scrapers import catalog
from scrapers.catalog import SERVICES, SITES, TOPICS


def _live_sids(site):
    return {e["sid"] for e in load_fixture(f"servicegroupservice_{SITES[site].webid}.json") if e["sid"]}


def test_every_etermin_service_is_in_catalog():
    for site in SITES:
        known = catalog.known_sids(site)
        missing = _live_sids(site) - known
        assert not missing, f"{site}: nicht im Katalog: {missing}"


def test_catalog_has_no_unknown_ids():
    for site in SITES:
        extra = catalog.known_sids(site) - _live_sids(site)
        assert not extra, f"{site}: im Katalog, aber nicht bei eTermin: {extra}"


def test_ids_are_unique_per_site():
    seen = set()
    for s in SERVICES.values():
        for sid in (s.sid, *s.aliases):
            assert (s.site, sid) not in seen, f"doppelt: {s.site} {sid}"
            seen.add((s.site, sid))


def test_topics_and_subtopics_valid():
    for s in SERVICES.values():
        topic = TOPICS[s.topic]
        if topic.subtopics:
            assert s.subtopic in topic.subtopics, f"{s.key}: Unterthema fehlt/ungültig"
        else:
            assert s.subtopic is None, f"{s.key}: Thema hat keine Unterthemen"
    for topic_key, topic in TOPICS.items():
        assert catalog.services_in(topic_key), f"Thema {topic_key} ist leer"
        for sub in topic.subtopics:
            assert catalog.services_in(topic_key, sub), f"Unterthema {topic_key}/{sub} ist leer"


def test_keys_fit_into_callback_data():
    for key in SERVICES:
        assert len(f"svc:{key}".encode()) <= 64
        assert key.isascii() and " " not in key


def test_button_names_are_short():
    for s in SERVICES.values():
        assert len(s.name) <= 45, f"{s.key}: Name zu lang für Button ({len(s.name)})"


@pytest.mark.parametrize("query, expected", [
    ("reisepass", "reisepass"),
    ("Personalausweis", "personalausweis"),
    ("perso", "personalausweis"),
    ("fuehrerschein umtausch", "fs_umtausch"),
    ("Führerschein Umtausch", "fs_umtausch"),
    ("wunschkennzeichen", "wunschkennzeichen"),
    ("gewerbe anmelden", "gewerbe_anmeldung"),
    ("umzug", "ummeldung"),
    ("Wiederzulassung", "wiederzulassung"),
    ("führungszeugnis", "fuehrungszeugnis"),
    ("ersterteilung", "bs_fs_antrag"),
    ("Führerschein beantragen", "bs_fs_antrag"),
    ("begleitetes fahren", "bs_fs_antrag"),
    ("führerschein erweiterung", "bs_fs_antrag"),
    ("neuerteilung", "bs_fs_antrag"),
])
def test_search_finds_expected_service(query, expected):
    results = catalog.search(query)
    assert expected in [s.key for s in results], [s.key for s in results]
    assert len(results) <= 8


def test_search_without_match_returns_empty():
    assert catalog.search("xyzabc") == []
    assert catalog.search("  ") == []


@pytest.mark.parametrize("calendar, expected", [
    ("Bürger-Service-Station-Hamborn_Slot2", "hamborn"),
    ("Bürger-Service-Station-Homberg/Ruhrort/Baerl", "homberg"),
    ("Bürger-Service-Station-Meiderich/Beeck_Slot8", "meiderich"),
    ("Bürger-Service-Station-Süd_Slot3", "sued"),
    ("Bürger-Service-Station-Mitte_Slot10", "mitte"),
    ("Fahrzeugzulassung Slot_1", None),
])
def test_location_from_calendar(calendar, expected):
    assert catalog.location_for_calendar(calendar) == expected


def test_booking_url_preselects_service():
    # Nur diese Form wählt die Dienstleistung vor und öffnet direkt den Kalender
    # (im Browser geprüft am 06.10.2026; "?serviceid=" wird ignoriert)
    assert catalog.booking_url(SERVICES["wiederzulassung"]) == \
        "https://www.etermin.net/stadt-duisburg-zul/serviceid/217884"
