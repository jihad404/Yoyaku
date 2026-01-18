from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.models import get_user_by_telegram_id, create_user, set_admin

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    # Prüfe ob Admin
    if telegram_id == ADMIN_ID:
        user = get_user_by_telegram_id(telegram_id)
        
        # Admin existiert noch nicht in DB -> erstellen
        if not user:
            create_user(
                telegram_id=telegram_id,
                first_name="Admin",
                last_name="Admin",
                birthdate="0000-00-00"
            )
            # Admin sofort freigeben und als Admin markieren
            set_admin(telegram_id)

        await update.message.reply_text(
            "Wilkommen Admin!\n\n"
            "Verfügbare Befehle:\n"
            "/start - Dieses Menü\n"
            "/pending - Offene Anfragen"
        )
        return
    
    # Normaler Nutzer
    user = get_user_by_telegram_id(telegram_id)

    if not user:
        # Nutzer existiert nicht -> Registrierung starten
        await update.message.reply_text(
            "Willkommen bei Yoyaku!\n\n"
            "Du bist noch nicht registriert.\n"
            "Bitte sende deine Daten im Format:\n\n"
            "/register Vorname Nachname Geburtsdatum\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1990"
        )
        return
    
    if user['is_approved'] == 0:
        # Nutzer wartet auf Freigabe
        await update.message.reply_text(
            "Deine Registrierung wird noch geprüft. \n"
            "Bitte warte auf die Freigabe durch einen Admin."
        )
        return
    
    # Nutzer ist Freigeschaltet
    await update.message.reply_text(
        "Wilkommen zurück!\n\n"
        "Verfügbare Befehle:\n"
        "/start - Dieses Menü\n"
        "/search - Neue Terminsuche starten\n"
        "/status - Aktive Suche anzeigen\n"
        "/stop - Suche beenden"
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    #Prüfe ob Nutzer schon existiert
    user = get_user_by_telegram_id(telegram_id)
    if user:
        await update.message.reply_text("Du bist bereits registriert.")
        return
    
    # context.args entählt die Argumente nach dem Befehl
    # /register Max Musermann 01.01.1990
    # context.args = ["Max", "Mustermann", "01.01.1900"]

    if len(context.args) < 3:
        await update.message.reply_text(
            "Bitte gib alle Daten an:\n"
            "/register Vorname Nachname Geburtsdatum\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1900"
        )
        return
    
    first_name = context.args[0]
    last_name = context.args[1]
    birthdate = context.args[2]

    # Nutzer erstellen
    create_user(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        birthdate=birthdate
    )

    # Nutzer informieren
    await update.message.reply_text(
        "Registrierung erfolgreich!\n\n"
        "Deine Daten:\n"
        f"Name: {first_name} {last_name}\n"
        f"Geburtsdatum: {birthdate}\n\n"
        "Ein Admin wird deine Anfrage prüfen, bitte habe etwas geduld."
    )

    # Admin benachrichtigen
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