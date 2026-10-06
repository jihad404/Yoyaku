"""Start, Registrierung und Admin-Freigabe. Die Terminsuche liegt in
bot/search_flow.py, /status und /stop in bot/searches.py."""
from datetime import date, datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.models import (
    MAX_ACTIVE_SEARCHES,
    approve_user,
    create_user,
    get_active_searches,
    get_pending_users,
    get_user_by_id,
    get_user_by_telegram_id,
    set_admin,
)

HELP_SEARCH = (
    "So geht's:\n"
    "/search – Termin suchen (Thema wählen)\n"
    "…oder einfach ein Stichwort schicken, z. B. „Reisepass“\n"
    "/status – Deine Suchen und freie Termine\n"
    "/stop – Suche beenden\n\n"
    "/start – Dieses Menü"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    # Admin-Erstellung beim ersten Start
    if telegram_id == ADMIN_ID and not get_user_by_telegram_id(telegram_id):
        create_user(telegram_id=telegram_id, first_name="Admin",
                    last_name="Admin", birthdate="0000-00-00")
        set_admin(telegram_id)

    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await update.message.reply_text(
            "Willkommen bei Yoyaku!\n\n"
            "Ich melde dir freie Termine bei der Stadt Duisburg – Bürgerservice, "
            "Führerschein, Zulassung und Gewerbe.\n\n"
            "Du bist noch nicht registriert.\n"
            "Registriere dich mit:\n\n"
            "/register Vorname Nachname Geburtsdatum\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1990"
        )
        return

    if user['is_approved'] != 1:
        await update.message.reply_text(
            "Deine Registrierung wird noch geprüft.\n"
            "Bitte warte auf die Freigabe durch einen Admin."
        )
        return

    count = len(get_active_searches(user['id']))
    greeting = "Willkommen Admin!" if telegram_id == ADMIN_ID else "Willkommen zurück!"
    searches_info = f"Aktive Suchen: {count}/{MAX_ACTIVE_SEARCHES}" if count else "Keine aktive Suche."
    admin_info = "Admin: /pending – Offene Registrierungsanfragen\n\n" if telegram_id == ADMIN_ID else ""

    await update.message.reply_text(f"{greeting}\n\n{searches_info}\n\n{admin_info}{HELP_SEARCH}")


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if user:
        await update.message.reply_text("Du bist bereits registriert.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Bitte gib alle Daten an:\n"
            "/register Vorname Nachname Geburtsdatum\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1990"
        )
        return

    first_name = context.args[0]
    last_name = " ".join(context.args[1:-1])
    birthdate = context.args[-1]

    try:
        parsed_birthdate = datetime.strptime(birthdate, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text(
            "Ungültiges Geburtsdatum. Bitte im Format TT.MM.JJJJ angeben.\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1990"
        )
        return

    if parsed_birthdate >= date.today() or parsed_birthdate.year < 1900:
        await update.message.reply_text("Bitte gib ein gültiges Geburtsdatum an.")
        return

    create_user(telegram_id=telegram_id, first_name=first_name,
                last_name=last_name, birthdate=birthdate)

    await update.message.reply_text(
        "Registrierung erfolgreich!\n\n"
        f"Name: {first_name} {last_name}\n"
        f"Geburtsdatum: {birthdate}\n\n"
        "Ein Admin wird deine Anfrage prüfen, bitte habe etwas Geduld."
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "Neue Registrierungsanfrage!\n\n"
            f"Name: {first_name} {last_name}\n"
            f"Geburtsdatum: {birthdate}\n"
            f"Telegram-ID: {telegram_id}\n\n"
            "Nutze /pending um Anfragen zu verwalten."
        )
    )


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    users = get_pending_users()

    if not users:
        await update.message.reply_text("Keine offenen Anfragen.")
        return

    text = "Offene Registrierungsanfragen:\n\n"
    for user in users:
        text += f"Name: {user['first_name']} {user['last_name']}\n"
        text += f"Geburtsdatum: {user['birthdate']}\n"
        text += f"Freigeben: /approve_{user['id']}\n\n"

    await update.message.reply_text(text)


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    user_id = int(update.message.text.split('_')[1])
    approved_user = get_user_by_id(user_id)
    if not approved_user:
        await update.message.reply_text(f"Nutzer {user_id} existiert nicht.")
        return
    if approved_user['is_approved'] == 1:
        await update.message.reply_text(f"Nutzer {user_id} ist bereits freigegeben.")
        return

    approve_user(user_id)
    await update.message.reply_text(
        f"Nutzer {user_id} ({approved_user['first_name']} {approved_user['last_name']}) wurde freigegeben."
    )

    try:
        await context.bot.send_message(
            chat_id=approved_user['telegram_id'],
            text=(
                "Deine Registrierung wurde bestätigt!\n"
                "Starte eine Terminsuche mit /search – oder schick mir einfach ein Stichwort, "
                "z. B. „Personalausweis“."
            )
        )
    except Exception:
        pass
