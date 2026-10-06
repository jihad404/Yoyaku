import threading
import time

# Jede Kategorie = eine Behörde mit einer Dienstleistung.
# "enabled": False blendet Kategorien aus, deren Scraper noch nicht existiert.
SEARCH_CATEGORIES = {
    1: {
        "name": "Zulassungsbehörde",
        "service_name": "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs",
        "scraper": "duisburg_zulassung",
        "booking_url": "https://www.etermin.net/stadt-duisburg-zul",
        "enabled": True,
    },
    2: {
        "name": "Ausländerbehörde",
        "service_name": "Aufenthaltstitel",
        "scraper": "duisburg_aufenthalt",
        "booking_url": None,
        "enabled": False,  # TODO: Scraper fehlt noch
    },
}

# Ergebnisse werden kurz zwischengespeichert, damit mehrere Suchen bzw.
# /status-Aufrufe nicht jeweils einen eigenen Chromium starten.
CACHE_TTL = 60

_cache: dict[str, tuple[float, dict]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def enabled_categories() -> dict:
    return {cid: c for cid, c in SEARCH_CATEGORIES.items() if c["enabled"]}


def category_for_scraper(scraper_name: str) -> dict | None:
    return next((c for c in SEARCH_CATEGORIES.values() if c["scraper"] == scraper_name), None)


def _scrape(scraper_name: str) -> dict:
    if scraper_name == "duisburg_zulassung":
        from scrapers.duisburg_zulassung import check_availability
        return check_availability(months_ahead=2)
    raise ValueError(f"Unbekannter Scraper: {scraper_name}")


def fetch_availability(scraper_name: str, max_age: float = CACHE_TTL) -> dict:
    """Liefert verfügbare Termine (synchron, für asyncio.to_thread).

    Pro Scraper läuft höchstens ein Abruf gleichzeitig; parallele Aufrufer
    warten und bekommen dann das zwischengespeicherte Ergebnis.
    """
    with _locks_guard:
        lock = _locks.setdefault(scraper_name, threading.Lock())

    with lock:
        cached = _cache.get(scraper_name)
        if cached and time.monotonic() - cached[0] < max_age:
            return cached[1]

        result = _scrape(scraper_name)
        _cache[scraper_name] = (time.monotonic(), result)
        return result
