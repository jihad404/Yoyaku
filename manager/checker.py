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
    searches = get_active_date_searches()

    if not searches:
        return

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
            deactivate_search(search_id)
            await context.bot.send_message(
                chat_id=telegram_id,
                text=(
                    f"Termin verfügbar!\n\n"
                    f"Dein Wunschtermin am {target.strftime('%d.%m.%Y')} ist jetzt buchbar.\n\n"
                    "Schnell buchen: https://www.etermin.net/stadt-duisburg-zul"
                )
            )
