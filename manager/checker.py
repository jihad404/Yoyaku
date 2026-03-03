import asyncio
from datetime import date

from database.models import get_active_date_searches, deactivate_search
from bot.handlers import _run_scraper

# Intervall in Sekunden (alle 5 Minuten prüfen)
CHECK_INTERVAL = 300


async def check_and_notify(context):
    """
    PTB JobQueue-Funktion: Prüft alle aktiven Wunschdatum-Suchen
    und benachrichtigt Nutzer wenn ihr Termin verfügbar ist.
    """
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checker läuft...")

    searches = get_active_date_searches()

    if not searches:
        print("  Keine aktiven Suchen.")
        return

    print(f"  {len(searches)} aktive Suche(n) gefunden.")

    for search in searches:
        search_id = search['id']
        target_str = search['target_date']       # "YYYY-MM-DD"
        telegram_id = search['telegram_id']
        scraper_name = search['search_type']

        try:
            target = date.fromisoformat(target_str)
        except ValueError:
            continue

        # Datum in der Vergangenheit → Suche beenden
        if target < date.today():
            deactivate_search(search_id)
            await context.bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"Deine Suche für den {target.strftime('%d.%m.%Y')} wurde beendet,\n"
                    "da das Datum inzwischen in der Vergangenheit liegt."
                )
            )
            continue

        # Scraper aufrufen (blockierend → Executor)
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _run_scraper, scraper_name
            )
        except Exception:
            continue

        # Wunschdatum verfügbar?
        if target_str in result["available_dates"]:
            from bot.handlers import SEARCH_TYPES, SEARCH_CATEGORIES
            type_info = next((t for t in SEARCH_TYPES.values() if t["scraper"] == scraper_name), None)
            service_name = type_info["name"] if type_info else scraper_name
            category_name = SEARCH_CATEGORIES[type_info["category"]] if type_info else ""

            deactivate_search(search_id)
            await context.bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"Termin verfügbar!\n\n"
                    f"Behörde: {category_name}\n"
                    f"Dienstleistung: {service_name}\n"
                    f"Datum: {target.strftime('%d.%m.%Y')}\n\n"
                    "Jetzt buchen: https://www.etermin.net/stadt-duisburg-zul"
                )
            )
