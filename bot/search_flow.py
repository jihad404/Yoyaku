"""Suche anlegen: Thema → (Unterthema) → Dienstleistung → (Standort) → Modus → (Datum).

Alle Schritte bearbeiten dieselbe Nachricht. Der Zwischenstand liegt in
context.user_data["draft"], ein erwartetes Datum in context.user_data["awaiting"].
"""
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from database.models import (
    MAX_ACTIVE_SEARCHES, create_search, find_duplicate_search, get_active_searches,
    get_user_by_telegram_id, log_error,
)
from manager.evaluate import initial_state
from manager.messages import mode_label, status_text
from scrapers import registry
from scrapers.catalog import (
    LOCATIONS, SERVICES, SITES, TOPICS, booking_url, search as search_catalog, service_label, services_in,
)
from scrapers.etermin import EterminError

DATE_HINT_DAYS = 14
MAX_DAYS_AHEAD = 365


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def approved_user(update: Update):
    user = get_user_by_telegram_id(update.effective_user.id)
    return user if user and user['is_approved'] == 1 else None


def _example_date() -> str:
    return (date.today() + timedelta(days=DATE_HINT_DAYS)).strftime('%d.%m.%Y')


def _rows(buttons, per_row=1):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _back(data):
    return [InlineKeyboardButton("« Zurück", callback_data=data)]


async def edit_message(query, text, markup=None):
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def _expired(query):
    await query.answer()
    await edit_message(query, "Diese Auswahl ist abgelaufen. Starte neu mit /search.")


def _service_back(service) -> str:
    """Wohin '« Zurück' aus Standort/Modus führt: zur Liste der Dienstleistung."""
    if TOPICS[service.topic].subtopics:
        return f"nav:st:{service.topic}:{service.subtopic}"
    return f"nav:t:{service.topic}"


# ---------------------------------------------------------------------------
# Tastaturen
# ---------------------------------------------------------------------------

TOPICS_TEXT = "Wähle ein Thema – oder tippe einfach ein Stichwort, z. B. „Reisepass“:"


def topics_keyboard():
    buttons = [InlineKeyboardButton(t.label, callback_data=f"nav:t:{t.key}") for t in TOPICS.values()]
    return InlineKeyboardMarkup(_rows(buttons, 2))


def services_keyboard(services, back):
    buttons = [InlineKeyboardButton(s.name, callback_data=f"svc:{s.key}") for s in services]
    return InlineKeyboardMarkup(_rows(buttons) + [_back(back)])


def location_keyboard(service):
    buttons = [InlineKeyboardButton("📍 Egal – alle Standorte", callback_data="loc:any")]
    loc_buttons = [InlineKeyboardButton(label, callback_data=f"loc:{key}") for key, label in LOCATIONS.items()]
    return InlineKeyboardMarkup([buttons] + _rows(loc_buttons, 2) + [_back(_service_back(service))])


def mode_keyboard(service):
    back = f"svc:{service.key}" if SITES[service.site].has_locations else _service_back(service)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ So früh wie möglich", callback_data="mode:earliest")],
        [InlineKeyboardButton("📅 Bis spätestens …", callback_data="mode:until")],
        [InlineKeyboardButton("🎯 Bestimmter Tag", callback_data="mode:day")],
        _back(back),
    ])


def until_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 Woche", callback_data="until:7"),
         InlineKeyboardButton("2 Wochen", callback_data="until:14"),
         InlineKeyboardButton("4 Wochen", callback_data="until:28")],
        [InlineKeyboardButton("✏️ Datum eingeben", callback_data="until:input")],
        _back("mode:back"),
    ])


def _draft_header(draft) -> str:
    service = SERVICES[draft["service"]]
    text = f"{service.name}\n{SITES[service.site].name}"
    if draft.get("location"):
        text += f" {LOCATIONS[draft['location']]}"
    return text


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------

async def _check_limit(user) -> str | None:
    if len(get_active_searches(user['id'])) >= MAX_ACTIVE_SEARCHES:
        return (f"Du hast bereits {MAX_ACTIVE_SEARCHES} aktive Suchen.\n"
                "Beende zuerst eine mit /stop.")
    return None


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = approved_user(update)
    if not user:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return
    limit_text = await _check_limit(user)
    if limit_text:
        await update.message.reply_text(limit_text)
        return
    context.user_data.pop("draft", None)
    context.user_data.pop("awaiting", None)
    await update.message.reply_text(TOPICS_TEXT, reply_markup=topics_keyboard())


async def on_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not approved_user(update):
        await query.answer("Du bist nicht freigeschaltet.", show_alert=True)
        return
    await query.answer()
    context.user_data.pop("awaiting", None)
    parts = query.data.split(":")

    if parts[1] == "home":
        await edit_message(query, TOPICS_TEXT, topics_keyboard())
        return

    topic = TOPICS.get(parts[2])
    if topic is None:
        await _expired(query)
        return

    if parts[1] == "t":
        if topic.subtopics:
            buttons = [InlineKeyboardButton(label, callback_data=f"nav:st:{topic.key}:{key}")
                       for key, label in topic.subtopics.items()]
            markup = InlineKeyboardMarkup(_rows(buttons, 2) + [_back("nav:home")])
            await edit_message(query, f"{topic.label}\nWähle einen Bereich:", markup)
        else:
            await edit_message(query, f"{topic.label}\nWähle eine Dienstleistung:",
                        services_keyboard(services_in(topic.key), "nav:home"))
        return

    if parts[1] == "st" and len(parts) == 4 and parts[3] in topic.subtopics:
        await edit_message(query, f"{topic.label} › {topic.subtopics[parts[3]]}\nWähle eine Dienstleistung:",
                    services_keyboard(services_in(topic.key, parts[3]), f"nav:t:{topic.key}"))
        return

    await _expired(query)


async def on_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not approved_user(update):
        await query.answer("Du bist nicht freigeschaltet.", show_alert=True)
        return
    service = SERVICES.get(query.data.split(":", 1)[1])
    if service is None:
        await _expired(query)
        return
    await query.answer()
    context.user_data.pop("awaiting", None)
    context.user_data["draft"] = {"service": service.key, "location": None}

    if SITES[service.site].has_locations:
        await edit_message(query, f"{_draft_header(context.user_data['draft'])}\n\nAn welchem Standort?",
                    location_keyboard(service))
    else:
        await edit_message(query, f"{_draft_header(context.user_data['draft'])}\n\nWelche Termine soll ich melden?",
                    mode_keyboard(service))


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    draft = context.user_data.get("draft")
    location = query.data.split(":", 1)[1]
    if not approved_user(update) or not draft or (location != "any" and location not in LOCATIONS):
        await _expired(query)
        return
    await query.answer()
    draft["location"] = None if location == "any" else location
    await edit_message(query, f"{_draft_header(draft)}\n\nWelche Termine soll ich melden?",
                mode_keyboard(SERVICES[draft["service"]]))


async def on_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    draft = context.user_data.get("draft")
    user = approved_user(update)
    if not user or not draft:
        await _expired(query)
        return
    mode = query.data.split(":", 1)[1]
    context.user_data.pop("awaiting", None)

    if mode == "back":
        await query.answer()
        await edit_message(query, f"{_draft_header(draft)}\n\nWelche Termine soll ich melden?",
                    mode_keyboard(SERVICES[draft["service"]]))
    elif mode == "earliest":
        await query.answer()
        await create_from_draft(context, user, "earliest", None, lambda t, m: edit_message(query, t, m))
    elif mode == "until":
        await query.answer()
        await edit_message(query, f"{_draft_header(draft)}\n\nBis wann brauchst du den Termin spätestens?",
                    until_keyboard())
    elif mode == "day":
        await query.answer()
        context.user_data["awaiting"] = "day"
        await edit_message(query, f"{_draft_header(draft)}\n\nSchick mir den gewünschten Tag als Nachricht, "
                           f"z. B. {_example_date()}", InlineKeyboardMarkup([_back("mode:back")]))
    else:
        await _expired(query)


async def on_until(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    draft = context.user_data.get("draft")
    user = approved_user(update)
    if not user or not draft:
        await _expired(query)
        return
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "input":
        context.user_data["awaiting"] = "until"
        await edit_message(query, f"{_draft_header(draft)}\n\nSchick mir das späteste Datum als Nachricht, "
                           f"z. B. {_example_date()}", InlineKeyboardMarkup([_back("mode:until")]))
        return
    if not choice.isdigit():
        await _expired(query)
        return
    target = date.today() + timedelta(days=int(choice))
    await create_from_draft(context, user, "until", target, lambda t, m: edit_message(query, t, m))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Freitext: entweder das erwartete Datum oder eine Stichwortsuche."""
    user = get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Bitte registriere dich zuerst – mehr dazu unter /start.")
        return
    if user['is_approved'] != 1:
        await update.message.reply_text("Deine Registrierung wird noch geprüft.")
        return

    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")
    if awaiting and context.user_data.get("draft"):
        await _handle_date_input(update, context, user, awaiting, text)
        return

    results = search_catalog(text)
    if not results:
        await update.message.reply_text(
            f"Zu „{text}“ habe ich nichts gefunden. Wähle ein Thema:", reply_markup=topics_keyboard())
        return
    await update.message.reply_text(f"Treffer für „{text}“:", reply_markup=services_keyboard(results, "nav:home"))


async def _handle_date_input(update, context, user, awaiting, text):
    try:
        target = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text(f"Bitte im Format TT.MM.JJJJ, z. B. {_example_date()}")
        return
    if target < date.today():
        await update.message.reply_text("Dieses Datum liegt in der Vergangenheit. Bitte ein anderes wählen.")
        return
    if target > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        await update.message.reply_text("Bitte ein Datum innerhalb der nächsten 12 Monate wählen.")
        return
    await create_from_draft(context, user, awaiting, target,
                            lambda t, m: update.message.reply_text(t, reply_markup=m))


# ---------------------------------------------------------------------------
# Suche anlegen
# ---------------------------------------------------------------------------

async def current_view(service, location, mode, target, availability=None):
    """Aktueller Stand: (Tage für die Anzeige, Tage für den Startzustand, Zeitfenster).
    Gibt None zurück, wenn eTermin gerade nicht erreichbar ist."""
    availability = availability or registry.availability
    today = date.today()
    try:
        days = await availability.days(service)
        if mode == "until":
            candidates = [d for d in days if today <= d <= target]
        elif mode == "day":
            candidates = [target] if target in days else []
        else:
            candidates = [d for d in days if d >= today]
        matching = await availability.matching_days(service, location, candidates,
                                                    limit=None if mode == "until" else 5)
        shown = matching[:5]
        slots_by_day = {d: await availability.slots(service, d, location) for d in shown}
    except EterminError as e:
        log_error(f"Anzeige {service.key}: {e}")
        return None
    return shown, matching, slots_by_day


async def create_from_draft(context, user, mode, target, respond):
    draft = context.user_data.get("draft")
    if not draft:
        await respond("Diese Auswahl ist abgelaufen. Starte neu mit /search.", None)
        return
    service = SERVICES[draft["service"]]
    location = draft.get("location")
    target_iso = target.isoformat() if target else None

    limit_text = await _check_limit(user)
    if limit_text:
        await respond(limit_text, None)
        return
    if find_duplicate_search(user['id'], service.key, mode, target_iso, location):
        await respond("Genau diese Suche läuft bereits. Den Stand siehst du mit /status.", None)
        return

    view = await current_view(service, location, mode, target)
    if view is None:
        state = {}  # nicht initialisiert → der Checker meldet beim ersten Lauf den Stand
        text_body = (f"✅ Suche gestartet\n{service_label(service, location)}\n"
                     f"Modus: {mode_label(mode, target)}\n\n"
                     "Den aktuellen Stand konnte ich gerade nicht abrufen – ich melde mich bei der nächsten Prüfung.")
    else:
        shown, matching, slots_by_day = view
        state = initial_state(mode, target, matching, datetime.now())
        text_body = status_text(service, location, mode, target, shown, slots_by_day, "✅ Suche gestartet")

    search_id = create_search(user['id'], service.key, mode, target_iso, location, state)
    context.user_data.pop("draft", None)
    context.user_data.pop("awaiting", None)

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("Jetzt buchen ↗", url=booking_url(service)),
        InlineKeyboardButton("Suche beenden", callback_data=f"stop:{search_id}"),
    ]])
    await respond(text_body, markup)
