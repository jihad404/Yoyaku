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

# Jede Kategorie = eine Behörde mit einer oder mehreren Dienstleistungen
SEARCH_CATEGORIES = {
    1: {
        "name": "Zulassungsbehörde",
        "service_name": "Wiederzulassung eines außer Betrieb gesetzten Fahrzeugs",
        "scraper": "duisburg_zulassung"
    },
    2: {
        "name": "Ausländerbehörde",
        "service_name": "Aufenthaltstitel",
        "scraper": "duisburg_aufenthalt"
    }
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _is_approved(user) -> bool:
    return user and user['is_approved'] == 1


def _active_search_info(search) -> str:
    """Gibt eine kurze Beschreibung der aktiven Suche zurück."""
    cat = next((c for c in SEARCH_CATEGORIES.values() if c["scraper"] == search['search_type']), None)
    name = cat["service_name"] if cat else search['search_type']
    target = search['target_date']
    target_info = f"\nWunschdatum: {datetime.fromisoformat(target).strftime('%d.%m.%Y')}" if target else ""
    return f"{name}{target_info}"


def _run_scraper(scraper_name: str) -> dict:
    """Führt den passenden Scraper aus (synchron, für run_in_executor)."""
    if scraper_name == "duisburg_zulassung":
        from scrapers.duisburg_zulassung import check_availability
        return check_availability(months_ahead=2)
    return {"available": False, "available_dates": []}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    # Admin-Erstellung beim ersten Start
    if telegram_id == ADMIN_ID:
        user = get_user_by_telegram_id(telegram_id)
        if not user:
            create_user(telegram_id=telegram_id, first_name="Admin",
                        last_name="Admin", birthdate="0000-00-00")
            set_admin(telegram_id)

        await update.message.reply_text(
            "Willkommen Admin!\n\n"
            "Admin-Befehle:\n"
            "/pending - Offene Registrierungsanfragen\n\n"
            "Suche:\n"
            "/search - Neue Terminsuche starten\n"
            "/status - Verfügbare Termine anzeigen\n"
            "/search_date - Wunschdatum setzen\n"
            "/stop - Suche beenden\n\n"
            "/start - Dieses Menü"
        )
        return

    user = get_user_by_telegram_id(telegram_id)

    if not user:
        await update.message.reply_text(
            "Willkommen bei Yoyaku!\n\n"
            "Du bist noch nicht registriert.\n"
            "Registriere dich mit:\n\n"
            "/register Vorname Nachname Geburtsdatum\n\n"
            "Beispiel:\n"
            "/register Max Mustermann 01.01.1990"
        )
        return

    if not _is_approved(user):
        await update.message.reply_text(
            "Deine Registrierung wird noch geprüft.\n"
            "Bitte warte auf die Freigabe durch einen Admin."
        )
        return

    active_search = get_active_search(user['id'])

    if active_search:
        info = _active_search_info(active_search)
        await update.message.reply_text(
            f"Willkommen zurück!\n\n"
            f"Aktive Suche:\n{info}\n\n"
            "Befehle:\n"
            "/status - Verfügbare Termine anzeigen\n"
            "/search_date - Wunschdatum setzen\n"
            "/stop - Suche beenden\n\n"
            "/start - Dieses Menü"
        )
    else:
        await update.message.reply_text(
            "Willkommen zurück!\n\n"
            "Keine aktive Suche.\n\n"
            "Befehle:\n"
            "/search - Neue Terminsuche starten\n\n"
            "/start - Dieses Menü"
        )


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
    last_name = context.args[1]
    birthdate = context.args[2]

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
    approve_user(user_id)
    await update.message.reply_text(f"Nutzer {user_id} wurde freigegeben.")

    approved_user = get_user_by_id(user_id)
    try:
        await context.bot.send_message(
            chat_id=approved_user['telegram_id'],
            text=(
                "Deine Registrierung wurde bestätigt!\n"
                "Starte eine Terminsuche mit /search."
            )
        )
    except Exception:
        pass


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt die verfügbaren Behörden-Kategorien."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    if get_active_search(user['id']):
        await update.message.reply_text(
            "Du hast bereits eine aktive Suche.\n"
            "Nutze /stop um sie zuerst zu beenden."
        )
        return

    text = "Wähle eine Behörde:\n\n"
    for cat_id, cat in SEARCH_CATEGORIES.items():
        text += f"{cat_id} - {cat['name']}\n"
        text += f"   {cat['service_name']}\n"
        text += f"   → /search_{cat_id}\n\n"

    await update.message.reply_text(text)


async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nutzer hat eine Kategorie gewählt → nach Datumspräferenz fragen."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    if get_active_search(user['id']):
        await update.message.reply_text(
            "Du hast bereits eine aktive Suche.\n"
            "Nutze /stop um sie zuerst zu beenden."
        )
        return

    cat_id = int(update.message.text.split('_')[1])

    if cat_id not in SEARCH_CATEGORIES:
        await update.message.reply_text("Ungültige Auswahl.")
        return

    cat = SEARCH_CATEGORIES[cat_id]

    # Kategorie im User-State merken, bis Datumspräferenz beantwortet
    context.user_data['pending_cat_id'] = cat_id

    await update.message.reply_text(
        f"Behörde: {cat['name']}\n"
        f"Dienstleistung: {cat['service_name']}\n\n"
        "Suchst du einen bestimmten Termin oder soll ich alle verfügbaren Termine melden?\n\n"
        "/search_any - Alle verfügbaren Termine melden\n"
        "/search_date TT.MM.JJJJ - Bestimmten Termin suchen\n\n"
        "Beispiel: /search_date 15.03.2026"
    )


async def search_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Startet eine Suche ohne Wunschdatum — meldet alle Terminänderungen."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    cat_id = context.user_data.get('pending_cat_id')
    if not cat_id or cat_id not in SEARCH_CATEGORIES:
        await update.message.reply_text(
            "Bitte wähle zuerst eine Behörde mit /search."
        )
        return

    if get_active_search(user['id']):
        await update.message.reply_text(
            "Du hast bereits eine aktive Suche.\n"
            "Nutze /stop um sie zuerst zu beenden."
        )
        return

    cat = SEARCH_CATEGORIES[cat_id]
    create_search(user['id'], cat['scraper'])
    context.user_data.pop('pending_cat_id', None)

    await update.message.reply_text(
        f"Suche gestartet!\n\n"
        f"Behörde: {cat['name']}\n"
        f"Dienstleistung: {cat['service_name']}\n\n"
        "Du wirst benachrichtigt sobald sich Termine ändern.\n\n"
        "Befehle:\n"
        "/status - Verfügbare Termine jetzt anzeigen\n"
        "/stop - Suche beenden"
    )


async def search_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Startet eine Suche mit Wunschdatum."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    cat_id = context.user_data.get('pending_cat_id')
    if not cat_id or cat_id not in SEARCH_CATEGORIES:
        await update.message.reply_text(
            "Bitte wähle zuerst eine Behörde mit /search."
        )
        return

    if get_active_search(user['id']):
        await update.message.reply_text(
            "Du hast bereits eine aktive Suche.\n"
            "Nutze /stop um sie zuerst zu beenden."
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
            "Dieses Datum liegt in der Vergangenheit.\n"
            "Bitte wähle ein zukünftiges Datum."
        )
        return

    cat = SEARCH_CATEGORIES[cat_id]
    create_search(user['id'], cat['scraper'], target_date=target.isoformat())
    context.user_data.pop('pending_cat_id', None)

    await update.message.reply_text(
        f"Suche gestartet!\n\n"
        f"Behörde: {cat['name']}\n"
        f"Dienstleistung: {cat['service_name']}\n"
        f"Wunschdatum: {target.strftime('%d.%m.%Y')}\n\n"
        "Du wirst benachrichtigt sobald dieser Termin verfügbar oder nicht mehr verfügbar ist.\n\n"
        "Befehle:\n"
        "/status - Verfügbare Termine jetzt anzeigen\n"
        "/stop - Suche beenden"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    active_search = get_active_search(user['id'])
    if not active_search:
        await update.message.reply_text("Du hast keine aktive Suche.")
        return

    deactivate_search(active_search['id'])
    context.user_data.pop('pending_cat_id', None)
    await update.message.reply_text(
        "Suche beendet.\n"
        "Starte eine neue Suche mit /search."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt alle aktuell verfügbaren Termine (ruft Scraper auf)."""
    telegram_id = update.effective_user.id
    user = get_user_by_telegram_id(telegram_id)

    if not _is_approved(user):
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return

    active_search = get_active_search(user['id'])
    if not active_search:
        await update.message.reply_text(
            "Du hast keine aktive Suche.\n"
            "Starte eine mit /search."
        )
        return

    await update.message.reply_text("Suche läuft... einen Moment bitte.")

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _run_scraper, active_search['search_type']
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
