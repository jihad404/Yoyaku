import asyncio
import json
from datetime import date, datetime

from telegram.error import Forbidden, TelegramError

from database.models import (
    get_all_active_searches, deactivate_search, update_last_known_dates, log_error,
)
from scrapers.registry import category_for_scraper, fetch_availability

# Intervall in Sekunden (alle 5 Minuten prüfen)
CHECK_INTERVAL = 300

# Ein leeres Ergebnis, obwohl vorher Termine bekannt waren, ist oft nur ein
# Ladefehler der Seite. Erst nach so vielen leeren Läufen in Folge melden wir
# "alle Termine weg".
EMPTY_RUNS_BEFORE_REMOVAL = 2

_empty_streak: dict[str, int] = {}


def _format_date(date_str: str) -> str:
    """YYYY-MM-DD → TT.MM.JJJJ"""
    return datetime.fromisoformat(date_str).strftime("%d.%m.%Y")


async def _send(context, search, text) -> None:
    """Sendet eine Nachricht; Fehler brechen die Prüfrunde nicht ab."""
    try:
        await context.bot.send_message(chat_id=search['telegram_id'], text=text)
    except Forbidden:
        # Nutzer hat den Bot blockiert → Suche beenden
        deactivate_search(search['id'])
        log_error(f"Bot blockiert, Suche {search['id']} beendet", search['user_id'])
    except TelegramError as e:
        log_error(f"Senden fehlgeschlagen (Suche {search['id']}): {e}", search['user_id'])


async def _get_results(scraper_names) -> dict:
    """Ruft jeden Scraper einmal pro Runde ab. Fehlgeschlagene fehlen im Ergebnis."""
    results = {}
    for name in scraper_names:
        try:
            result = await asyncio.to_thread(fetch_availability, name)
        except Exception as e:
            print(f"  Scraper-Fehler ({name}): {e}")
            log_error(f"Scraper {name}: {e!r}")
            continue

        dates = set(result["available_dates"])
        if dates:
            _empty_streak[name] = 0
        else:
            _empty_streak[name] = _empty_streak.get(name, 0) + 1
        results[name] = dates
    return results


async def check_and_notify(context):
    """
    PTB JobQueue-Funktion: Prüft alle aktiven Suchen auf Änderungen
    und benachrichtigt Nutzer bei neuen oder weggefallenen Terminen.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checker läuft...")

    searches = get_all_active_searches()

    if not searches:
        print("  Keine aktiven Suchen.")
        return

    print(f"  {len(searches)} aktive Suche(n) gefunden.")

    # Abgelaufene Wunschdaten zuerst beenden
    remaining = []
    for search in searches:
        target_str = search['target_date']
        if target_str:
            try:
                expired = date.fromisoformat(target_str) < date.today()
            except ValueError:
                log_error(f"Ungültiges Wunschdatum in Suche {search['id']}: {target_str}", search['user_id'])
                continue
            if expired:
                deactivate_search(search['id'])
                await _send(context, search, (
                    "Suche beendet.\n\n"
                    f"Dein Wunschtermin am {_format_date(target_str)} "
                    "liegt inzwischen in der Vergangenheit.\n"
                    "Starte eine neue Suche mit /search."
                ))
                continue
        remaining.append(search)

    results = await _get_results({s['search_type'] for s in remaining})

    for search in remaining:
        scraper_name = search['search_type']
        if scraper_name not in results:
            continue
        current_dates = results[scraper_name]

        try:
            last_known = set(json.loads(search['last_known_dates'])) if search['last_known_dates'] else None
        except (TypeError, json.JSONDecodeError):
            last_known = None

        cat = category_for_scraper(scraper_name) or {}

        # Erste Prüfung: aktuellen Stand speichern und sofort melden
        if last_known is None:
            update_last_known_dates(search['id'], sorted(current_dates))
            await _notify_initial(context, search, current_dates, cat)
            continue

        # Vermutlicher Ladefehler: leeres Ergebnis noch nicht übernehmen
        if not current_dates and last_known and _empty_streak.get(scraper_name, 0) < EMPTY_RUNS_BEFORE_REMOVAL:
            continue

        new_dates = current_dates - last_known
        removed_dates = last_known - current_dates

        if not new_dates and not removed_dates:
            continue

        update_last_known_dates(search['id'], sorted(current_dates))

        if search['target_date']:
            await _notify_target_date(context, search, new_dates, removed_dates, cat)
        else:
            await _notify_general(context, search, new_dates, removed_dates, cat)


def _available_text(target_str, cat) -> str:
    text = (
        "Termin verfügbar!\n\n"
        f"Behörde: {cat.get('name', '')}\n"
        f"Dienstleistung: {cat.get('service_name', '')}\n"
        f"Datum: {_format_date(target_str)}\n\n"
    )
    if cat.get('booking_url'):
        text += f"Jetzt buchen: {cat['booking_url']}\n\n"
    return text + "Die Suche läuft weiter und meldet erneut falls sich etwas ändert."


async def _notify_initial(context, search, current_dates, cat):
    """Meldet den Stand bei der ersten Prüfung einer neuen Suche."""
    target_str = search['target_date']
    if target_str:
        if target_str in current_dates:
            await _send(context, search, _available_text(target_str, cat))
        return

    if current_dates:
        await _notify_general(context, search, current_dates, set(), cat, title="Aktuell verfügbar")


async def _notify_target_date(context, search, new_dates, removed_dates, cat):
    """Benachrichtigt bei Änderungen am Wunschdatum."""
    target_str = search['target_date']
    if target_str in new_dates:
        await _send(context, search, _available_text(target_str, cat))
    elif target_str in removed_dates:
        await _send(context, search, (
            "Termin nicht mehr verfügbar.\n\n"
            f"Dein Wunschtermin am {_format_date(target_str)} "
            "ist leider nicht mehr buchbar.\n"
            "Die Suche läuft weiter."
        ))


async def _notify_general(context, search, new_dates, removed_dates, cat, title="Terminänderung"):
    """Benachrichtigt über alle Terminänderungen."""
    lines = [f"{title} — {cat.get('service_name', search['search_type'])}:\n"]

    if new_dates:
        lines.append("Neu verfügbar:")
        for d in sorted(new_dates):
            lines.append(f"  + {_format_date(d)}")

    if removed_dates:
        if new_dates:
            lines.append("")
        lines.append("Nicht mehr verfügbar:")
        for d in sorted(removed_dates):
            lines.append(f"  - {_format_date(d)}")

    if new_dates and cat.get('booking_url'):
        lines.append(f"\nJetzt buchen: {cat['booking_url']}")

    await _send(context, search, "\n".join(lines))
