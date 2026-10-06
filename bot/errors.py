"""Zentraler Fehler-Handler: unerwartete Fehler in Bot-Befehlen werden geloggt,
in error_logs gespeichert und dem Admin gemeldet (höchstens alle 10 Minuten)."""
import logging
import time

from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.models import get_user_by_telegram_id, log_error

logger = logging.getLogger(__name__)

ADMIN_ALERT_INTERVAL = 10 * 60
_last_admin_alert = 0.0

# Harmlose Telegram-Meldungen, die keinen Alarm wert sind
_HARMLESS = ("query is too old", "message is not modified")


def _describe(update) -> tuple[str, int | None]:
    """Kurzbeschreibung des Updates ohne personenbezogene Daten."""
    if not hasattr(update, "effective_user"):
        return "kein Update", None
    user = get_user_by_telegram_id(update.effective_user.id) if update.effective_user else None
    user_id = user['id'] if user else None
    if update.callback_query:
        return f"Button {update.callback_query.data!r}", user_id
    if update.message and update.message.text and update.message.text.startswith("/"):
        return f"Befehl {update.message.text.split()[0]!r}", user_id
    return "Nachricht", user_id


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_admin_alert
    error = context.error

    if isinstance(error, BadRequest) and any(h in str(error).lower() for h in _HARMLESS):
        logger.info("Harmloser Telegram-Fehler: %s", error)
        return
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("Netzwerkproblem mit Telegram: %s", error)
        return

    what, user_id = _describe(update)
    logger.error("Fehler bei %s (Nutzer %s)", what, user_id, exc_info=error)
    reference = log_error(f"{what}: {error!r}", user_id)

    if getattr(update, "effective_chat", None):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Da ist leider etwas schiefgelaufen. Bitte versuche es noch einmal.\nFehlerreferenz: {reference}",
            )
        except Exception:
            logger.warning("Fehlermeldung an Nutzer %s nicht zustellbar", user_id)

    now = time.monotonic()
    if now - _last_admin_alert >= ADMIN_ALERT_INTERVAL:
        _last_admin_alert = now
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🐞 Fehler im Bot ({what}): {type(error).__name__}\nReferenz: {reference}\n"
                     "Details in logs/yoyaku.log",
            )
        except Exception:
            logger.warning("Admin-Benachrichtigung über Fehler fehlgeschlagen")
