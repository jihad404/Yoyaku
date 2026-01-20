from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.models import (
    get_user_by_telegram_id, 
    get_user_by_id, create_user, 
    set_admin, get_pending_users, 
    approve_user, 
    get_active_search,
    create_search
    )

  # Verfügbare Terminarten
SEARCH_TYPES = {
    1: {
        "name": "Duisburg - Aufenthaltstitel",
        "scraper": "duisburg_aufenthalt"
    }
}

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


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    # Nur Admin darf das
    if telegram_id != ADMIN_ID:
        return

    # Hole alle wartenden Nutzer
    users = get_pending_users()

    # Keine Nutzer? Fertig.
    if not users:
        await update.message.reply_text("Keine Anfragen.")
        return

    # Text aufbauen
    text = "Wartende Nutzer:\n\n"

    for user in users:
        text += f"Name: {user['first_name']} {user['last_name']}\n"
        text += f"Geburtsdatum: {user['birthdate']}\n"
        text += f"Freigeben: /approve_{user['id']}\n"
        text += "\n"

    # Fertigen Text senden
    await update.message.reply_text(text)


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gibt einen Nutzer frei. Nur für Admin."""
    telegram_id = update.effective_user.id

    # Nur Admin darf das
    if telegram_id != ADMIN_ID:
        return

    # ID aus Befehl extrahieren (/approve_5 -> 5)
    reply = update.message.text.split('_')
    user_id = int(reply[1])

    # Nutzer in Datenbank freigeben
    approve_user(user_id)

    # Admin bestätigen
    await update.message.reply_text(f"Nutzer {user_id} wurde freigegeben.")

    # Nutzer informieren
    approved_user = get_user_by_id(user_id)

    try:
        await context.bot.send_message(
            chat_id=approved_user['telegram_id'],
            text=(
                "Hey! Der Admin hat deine Anfrage bestätigt.\n"
                "Du kannst nun eine Terminsuche starten.\n"
                "Schreibe /start um anzufangen!"
            )
        )
    except:
        pass  # Nutzer hat Bot blockiert


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt verfügbare Terminarten."""
    telegram_id = update.effective_user.id

    # Nutzer prüfen
    user = get_user_by_telegram_id(telegram_id)

    if not user or user['is_approved'] == 0:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return
      
    # Prüfe ob schon eine Suche läuft
    active_search = get_active_search(user['id'])
 
    if active_search:
        await update.message.reply_text(
            "Du hast bereits eine aktive Suche.\n"
            "Nutze /stop um sie zu beenden."
        )
        return
 
    # Verfügbare Terminarten anzeigen
    text = "Verfügbare Terminarten:\n\n"
 
    for type_id, type_info in SEARCH_TYPES.items():
        text += f"{type_id}. {type_info['name']}\n"
        text += f"   → /search_{type_id}\n\n"

    await update.message.reply_text(text)


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
      """Startet eine Terminsuche."""
      telegram_id = update.effective_user.id

      # Nutzer prüfen
      user = get_user_by_telegram_id(telegram_id)

      if not user or user['is_approved'] == 0:
          await update.message.reply_text("Du bist nicht freigeschaltet.")
          return

      # Prüfe ob schon eine Suche läuft
      active_search = get_active_search(user['id'])

      if active_search:
          await update.message.reply_text(
              "Du hast bereits eine aktive Suche.\n"
              "Nutze /stop um sie zu beenden."
          )
          return

      # ID aus Befehl extrahieren (/search_1 -> 1)
      reply = update.message.text.split('_')
      type_id = int(reply[1])

      # Prüfe ob Terminart existiert
      if type_id not in SEARCH_TYPES:
          await update.message.reply_text("Ungültige Terminart.")
          return

      search_type = SEARCH_TYPES[type_id]

      # Suche in Datenbank erstellen
      search_id = create_search(user['id'], search_type['scraper'])

      await update.message.reply_text(
          f"🔍 Suche gestartet!\n\n"
          f"Terminart: {search_type['name']}\n"
          f"Such-ID: {search_id}\n\n"
          "Du wirst benachrichtigt sobald ein Termin gefunden wird.\n"
          "Nutze /stop um die Suche zu beenden."
      )

      # TODO: Hier später den Scraper starten