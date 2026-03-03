import asyncio
from datetime import date, datetime
from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.models import (
    get_user_by_telegram_id,
    get_user_by_id, create_user,
    set_admin, get_pending_users,
    approve_user,
    get_active_search,
    create_search,
    set_search_target_date,
    deactivate_search,
)

# Behördenkategorien
SEARCH_CATEGORIES = {
    1: "Zulassungsbehörde",
    2: "Ausländerbehörde",
}

# Verfügbare Terminarten
SEARCH_TYPES = {
    1: {
        "name": "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs",
        "category": 1,
        "scraper": "duisburg_zulassung"
    },
    2: {
        "name": "Aufenthaltstitel",
        "category": 2,
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
            "Willkommen Admin!\n\n"
            "Befehle:\n"
            "/pending - Offene Registrierungsanfragen\n"
            "/start - Dieses Menü"
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
    
    # Nutzer ist freigeschaltet
    active_search = get_active_search(user['id'])

    if active_search:
        search_name = next(
            (t["name"] for t in SEARCH_TYPES.values() if t["scraper"] == active_search['search_type']),
            active_search['search_type']
        )
        target = active_search['target_date']
        target_info = f"\nWunschdatum: {datetime.fromisoformat(target).strftime('%d.%m.%Y')}" if target else ""
        status_text = (
            f"Aktive Suche:\n"
            f"{search_name}{target_info}\n\n"
            "Befehle:\n"
            "/status - Verfügbare Termine anzeigen\n"
            "/search_date - Wunschdatum setzen\n"
            "/stop - Suche beenden\n"
            "/start - Dieses Menü"
        )
    else:
        status_text = (
            "Keine aktive Suche.\n\n"
            "Befehle:\n"
            "/search - Neue Terminsuche starten\n"
            "/start - Dieses Menü"
        )

    await update.message.reply_text(f"Willkommen zurück!\n\n{status_text}")

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
 
    # Terminarten nach Kategorie gruppiert anzeigen
    text = "Terminvereinbarung — Bitte wähle eine Dienstleistung:\n"

    current_category = None
    for type_id, type_info in SEARCH_TYPES.items():
        cat_id = type_info["category"]
        if cat_id != current_category:
            current_category = cat_id
            text += f"\n{SEARCH_CATEGORIES[cat_id]}:\n"
        text += f"  • {type_info['name']}\n"
        text += f"    → /search_{type_id}\n"

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

      category_name = SEARCH_CATEGORIES[search_type['category']]

      await update.message.reply_text(
          f"Suche gestartet!\n\n"
          f"Behörde: {category_name}\n"
          f"Dienstleistung: {search_type['name']}\n\n"
          "Nächste Schritte:\n"
          "/status - Alle freien Termine jetzt anzeigen\n"
          "/search_date - Nach einem bestimmten Datum suchen\n"
          "/stop - Suche beenden"
      )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Beendet die aktive Suche des Nutzers."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not user or user['is_approved'] == 0:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    active_search = get_active_search(user['id'])

    if not active_search:
        await update.message.reply_text("Du hast keine aktive Suche.")
        return

    deactivate_search(active_search['id'])
    await update.message.reply_text("Suche beendet.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt alle aktuell verfügbaren Termine (ruft Scraper auf)."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not user or user['is_approved'] == 0:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    active_search = get_active_search(user['id'])

    if not active_search:
        await update.message.reply_text(
            "Du hast keine aktive Suche.\n"
            "Starte zuerst eine Suche mit /search."
        )
        return

    await update.message.reply_text("Suche läuft... einen Moment bitte.")

    try:
        scraper_name = active_search['search_type']
        result = await asyncio.get_event_loop().run_in_executor(
            None, _run_scraper, scraper_name
        )
    except Exception as e:
        await update.message.reply_text(f"Fehler beim Abrufen der Termine: {e}")
        return

    if result["available"]:
        dates = "\n".join(
            f"  • {datetime.fromisoformat(d).strftime('%d.%m.%Y')}"
            for d in result["available_dates"]
        )
        await update.message.reply_text(f"Verfügbare Termine:\n\n{dates}")
    else:
        await update.message.reply_text("Derzeit keine Termine verfügbar.")


async def search_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Setzt ein Wunschdatum für die aktive Suche."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not user or user['is_approved'] == 0:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    active_search = get_active_search(user['id'])

    if not active_search:
        await update.message.reply_text(
            "Du hast keine aktive Suche.\n"
            "Starte zuerst eine Suche mit /search."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Bitte gib ein Datum an:\n"
            "/search_date TT.MM.JJJJ\n\n"
            "Beispiel: /search_date 15.03.2026"
        )
        return

    try:
        target = datetime.strptime(context.args[0], "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text(
            "Ungültiges Datum. Bitte im Format TT.MM.JJJJ angeben.\n"
            "Beispiel: /search_date 15.03.2026"
        )
        return

    if target < date.today():
        await update.message.reply_text(
            "Dieses Datum liegt in der Vergangenheit. "
            "Bitte wähle ein zukünftiges Datum."
        )
        return

    set_search_target_date(active_search['id'], target.isoformat())

    await update.message.reply_text(
        f"Wunschdatum gesetzt: {target.strftime('%d.%m.%Y')}\n\n"
        "Du wirst benachrichtigt sobald dieser Termin verfügbar ist.\n"
        "Nutze /stop um die Suche zu beenden."
    )


def _run_scraper(scraper_name: str) -> dict:
    """Führt den passenden Scraper aus (synchron, für run_in_executor)."""
    if scraper_name == "duisburg_zulassung":
        from scrapers.duisburg_zulassung import check_availability
        return check_availability(months_ahead=2)
    # Weitere Scraper hier ergänzen
    return {"available": False, "available_dates": []}