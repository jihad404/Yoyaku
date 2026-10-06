import logging
import os
from datetime import time

from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, PicklePersistence, filters,
)

from config import BOT_TOKEN
from bot.errors import on_error
from bot.handlers import approve, pending, register, start
from bot.search_flow import on_location, on_mode, on_navigation, on_service, on_text, on_until, search_command
from bot.searches import on_list, on_show, on_stop, on_stop_all, status_command, stop_command
from manager.catalog_sync import sync_catalog
from manager.checker import CHECK_INTERVAL, check_and_notify
from scrapers import registry

try:
    from zoneinfo import ZoneInfo
    TIMEZONE = ZoneInfo("Europe/Berlin")
except Exception:  # ohne Zeitzonendaten (z. B. Windows ohne tzdata) in UTC
    TIMEZONE = None

CATALOG_SYNC_TIME = time(6, 0, tzinfo=TIMEZONE)

logger = logging.getLogger(__name__)


async def _shutdown(app: Application):
    await registry.availability.close()


def main():
    # Persistenz, damit z. B. eine angefangene Suche einen Neustart übersteht
    persistence = PicklePersistence(
        filepath=os.path.join(os.path.dirname(__file__), '..', 'bot_state.pickle')
    )
    # concurrent_updates: eine langsame eTermin-Abfrage blockiert nicht die Klicks anderer Nutzer
    app = (Application.builder().token(BOT_TOKEN).persistence(persistence)
           .concurrent_updates(True).post_shutdown(_shutdown).build())

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(MessageHandler(filters.Regex(r'^/approve_\d+$'), approve))

    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))

    app.add_handler(CallbackQueryHandler(on_navigation, pattern=r"^nav:"))
    app.add_handler(CallbackQueryHandler(on_service, pattern=r"^svc:"))
    app.add_handler(CallbackQueryHandler(on_location, pattern=r"^loc:"))
    app.add_handler(CallbackQueryHandler(on_mode, pattern=r"^mode:"))
    app.add_handler(CallbackQueryHandler(on_until, pattern=r"^until:"))
    app.add_handler(CallbackQueryHandler(on_show, pattern=r"^show:"))
    app.add_handler(CallbackQueryHandler(on_list, pattern=r"^list:"))
    app.add_handler(CallbackQueryHandler(on_stop, pattern=r"^stopl?:"))
    app.add_handler(CallbackQueryHandler(on_stop_all, pattern=r"^stopall$"))

    # Freitext (keine Befehle): Datumseingabe oder Stichwortsuche
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(on_error)

    app.job_queue.run_repeating(check_and_notify, interval=CHECK_INTERVAL, first=30)
    app.job_queue.run_daily(sync_catalog, time=CATALOG_SYNC_TIME)

    logger.info("Bot startet (Prüfintervall %s s)...", CHECK_INTERVAL)
    app.run_polling()


if __name__ == "__main__":
    main()
