import logging
import time
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError

from config import ADMIN_ID
from database.models import (
    deactivate_all_searches, deactivate_search, get_all_active_searches, load_state, log_error,
    update_search_state,
)
from manager.evaluate import evaluate
from manager.messages import moved_text, notification_text
from scrapers import registry
from scrapers.catalog import MOVED, SERVICES, SITES, booking_url
from scrapers.etermin import EterminError

logger = logging.getLogger(__name__)

# Intervall in Sekunden
CHECK_INTERVAL = 180

# Ein leeres Ergebnis, obwohl vorher Termine bekannt waren, ist oft nur ein
# Ladefehler. Erst nach so vielen leeren Abfragen in Folge wird es übernommen.
EMPTY_RUNS_BEFORE_REMOVAL = 2

# Nach so vielen fehlgeschlagenen Runden einer Buchungsseite wird der Admin informiert
FAILURE_ALERT_ROUNDS = 3

_empty_streak: dict[str, int] = {}
_site_failures: dict[str, int] = {}
_site_alerted: set[str] = set()


def _keyboard(service, search_id, include_stop=True):
    buttons = [InlineKeyboardButton("Jetzt buchen ↗", url=booking_url(service))]
    if include_stop:
        buttons.append(InlineKeyboardButton("Suche beenden", callback_data=f"stop:{search_id}"))
    return InlineKeyboardMarkup([buttons])


async def send_to_user(context, search, text, reply_markup=None) -> bool:
    """Sendet eine Nachricht; Fehler brechen die Prüfrunde nicht ab.
    Gibt zurück, ob die Nachricht zugestellt wurde."""
    try:
        await context.bot.send_message(chat_id=search['telegram_id'], text=text, reply_markup=reply_markup)
        return True
    except Forbidden:
        # Nutzer hat den Bot blockiert → alle seine Suchen beenden
        logger.warning("Nutzer %s hat den Bot blockiert, Suchen beendet", search['user_id'])
        deactivate_all_searches(search['user_id'])
        log_error(f"Bot blockiert, Suchen von Nutzer {search['user_id']} beendet", search['user_id'])
    except TelegramError as e:
        logger.warning("Senden an Nutzer %s fehlgeschlagen (Suche %s): %s", search['user_id'], search['id'], e)
        log_error(f"Senden fehlgeschlagen (Suche {search['id']}): {e}", search['user_id'])
    return False


async def _notify_admin(context, text) -> None:
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=text)
    except TelegramError as e:
        log_error(f"Admin-Nachricht fehlgeschlagen: {e}")


async def _update_site_health(context, ok_sites: set, failed_sites: set) -> None:
    for site in failed_sites - ok_sites:
        _site_failures[site] = _site_failures.get(site, 0) + 1
        if _site_failures[site] >= FAILURE_ALERT_ROUNDS and site not in _site_alerted:
            _site_alerted.add(site)
            logger.error("%s seit %s Runden nicht erreichbar", SITES[site].name, _site_failures[site])
            await _notify_admin(context, (
                f"⚠️ eTermin-Abfrage für {SITES[site].name} schlägt seit {_site_failures[site]} Runden fehl.\n"
                "Details stehen in error_logs. Möglicherweise hat sich die Schnittstelle geändert."
            ))
    for site in ok_sites:
        _site_failures[site] = 0
        if site in _site_alerted:
            _site_alerted.discard(site)
            logger.info("%s wieder erreichbar", SITES[site].name)
            await _notify_admin(context, f"✅ eTermin-Abfrage für {SITES[site].name} funktioniert wieder.")


async def _fetch_all(context, availability, service_keys) -> dict:
    """Fragt jede Dienstleistung einmal ab. Fehlgeschlagene fehlen im Ergebnis."""
    results = {}
    ok_sites, failed_sites = set(), set()
    for key in sorted(service_keys):
        service = SERVICES[key]
        try:
            days = await availability.days(service)
        except EterminError as e:
            logger.warning("eTermin-Fehler bei %s: %s", key, e)
            log_error(f"eTermin {key}: {e}")
            failed_sites.add(service.site)
            continue
        ok_sites.add(service.site)
        _empty_streak[key] = 0 if days else _empty_streak.get(key, 0) + 1
        results[key] = days
    await _update_site_health(context, ok_sites, failed_sites)
    return results


async def _candidate_days(availability, service, mode, target, location, days, today) -> list[date]:
    if mode == "earliest":
        return await availability.matching_days(service, location, [d for d in days if d >= today], limit=1)
    if mode == "until":
        return await availability.matching_days(service, location, [d for d in days if today <= d <= target])
    return await availability.matching_days(service, location, [target] if target in days else [])


async def check_search(context, availability, search, results: dict, now: datetime) -> None:
    service = SERVICES.get(search['search_type'])
    if service is None:
        return  # Dienstleistung nicht mehr im Katalog; der Katalogabgleich informiert

    mode = search['mode'] or 'earliest'
    target = date.fromisoformat(search['target_date']) if search['target_date'] else None
    location = search['location']
    state = load_state(search)
    today = now.date()

    moved_key = state.get("moved_from")
    if moved_key:
        # Beim Start umgestellte Suche (database/db.py): einmal erklären, dann normal
        # weiter – der leere Zustand meldet anschließend den aktuellen Stand
        moved = MOVED.get(moved_key)
        if moved and not await send_to_user(context, search, moved_text(moved, service, location),
                                            _keyboard(service, search['id'])):
            return  # nicht zugestellt → nächste Runde erneut versuchen
        state.pop("moved_from")
        update_search_state(search['id'], state)
        logger.info("Suche %s von %s auf %s umgestellt (Nutzer %s)", search['id'], moved_key,
                    service.key, search['user_id'])

    if mode in ("until", "day") and target < today:
        decision = evaluate(mode, target, state, [], now)
    else:
        if search['search_type'] not in results:
            return  # Abfrage in dieser Runde fehlgeschlagen
        days = results[search['search_type']]
        had_days = state.get("known") or state.get("earliest") or state.get("day_available")
        if not days and had_days and _empty_streak.get(service.key, 0) < EMPTY_RUNS_BEFORE_REMOVAL:
            return  # vermutlich Ladefehler, nächste Runde abwarten
        try:
            matching = await _candidate_days(availability, service, mode, target, location, days, today)
        except EterminError as e:
            log_error(f"eTermin Zeitfenster {service.key}: {e}", search['user_id'])
            return
        decision = evaluate(mode, target, state, matching, now)

    if decision.kind:
        slots_by_day = {}
        if decision.kind in ("earlier", "new_days", "day_available"):
            for day in decision.days[:5]:
                try:
                    slots_by_day[day] = await availability.slots(service, day, location)
                except EterminError:
                    pass  # Nachricht kommt dann ohne Uhrzeiten

        text = notification_text(service, location, decision, target, slots_by_day)
        markup = None if decision.end else _keyboard(service, search['id'])
        if not await send_to_user(context, search, text, markup):
            # Nicht zugestellt (z. B. Telegram gestört, Sendelimit): Zustand nicht speichern,
            # damit die nächste Runde dieselbe Meldung erneut versucht. Lieber im Zweifel
            # doppelt melden (Zeitüberschreitung nach erfolgter Zustellung) als gar nicht.
            return
        logger.info("Benachrichtigung '%s' für Suche %s (Nutzer %s, %s): %s", decision.kind, search['id'],
                    search['user_id'], service.key, [d.isoformat() for d in decision.days])

    update_search_state(search['id'], decision.state)
    if decision.end:
        deactivate_search(search['id'])


async def check_and_notify(context, availability=None, now: datetime | None = None):
    """PTB-JobQueue-Funktion: prüft alle aktiven Suchen und benachrichtigt bei Änderungen."""
    availability = availability or registry.availability
    now = now or datetime.now()
    started = time.monotonic()

    searches = get_all_active_searches()
    if not searches:
        logger.debug("Prüfrunde: keine aktiven Suchen")
        return

    service_keys = {s['search_type'] for s in searches if s['search_type'] in SERVICES}
    results = await _fetch_all(context, availability, service_keys)

    for search in searches:
        try:
            await check_search(context, availability, search, results, now)
        except Exception as e:  # eine kaputte Suche darf die Runde nicht stoppen
            logger.exception("Fehler bei Suche %s", search['id'])
            log_error(f"Checker Suche {search['id']}: {e!r}", search['user_id'])

    logger.info("Prüfrunde: %s Suche(n), %s Dienstleistung(en), %s fehlgeschlagen, %.1f s",
                len(searches), len(service_keys), len(service_keys) - len(results), time.monotonic() - started)
