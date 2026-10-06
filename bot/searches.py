"""Aktive Suchen anzeigen (/status) und beenden (/stop)."""
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.search_flow import approved_user, edit_message, current_view
from database.models import (
    MAX_ACTIVE_SEARCHES, deactivate_all_searches, deactivate_search, get_active_searches, get_search,
)
from manager.messages import status_text
from scrapers.catalog import LOCATIONS, SERVICES, booking_url

SHORT_MODE = {"earliest": "⚡", "until": "📅", "day": "🎯"}


def search_button_label(search) -> str:
    service = SERVICES.get(search['search_type'])
    name = service.name if service else search['search_type']
    parts = [SHORT_MODE.get(search['mode'], ""), name]
    if search['location']:
        parts.append(f"· {LOCATIONS.get(search['location'], search['location'])}")
    if search['target_date']:
        parts.append(f"· {date.fromisoformat(search['target_date']):%d.%m.}")
    return " ".join(p for p in parts if p)


def _status_list(searches):
    text = (f"Deine aktiven Suchen ({len(searches)}/{MAX_ACTIVE_SEARCHES}).\n"
            "Tippe auf eine Suche für den aktuellen Stand.")
    buttons = [[InlineKeyboardButton(search_button_label(s), callback_data=f"show:{s['id']}")] for s in searches]
    return text, InlineKeyboardMarkup(buttons)


def _stop_list(searches):
    text = "Welche Suche möchtest du beenden?"
    buttons = [[InlineKeyboardButton(f"⏹ {search_button_label(s)}", callback_data=f"stopl:{s['id']}")]
               for s in searches]
    if len(searches) > 1:
        buttons.append([InlineKeyboardButton("⏹ Alle beenden", callback_data="stopall")])
    return text, InlineKeyboardMarkup(buttons)


NO_SEARCHES = "Du hast keine aktiven Suchen.\nStarte eine mit /search."


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = approved_user(update)
    if not user:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return
    searches = get_active_searches(user['id'])
    if not searches:
        await update.message.reply_text(NO_SEARCHES)
        return
    text, markup = _status_list(searches)
    await update.message.reply_text(text, reply_markup=markup)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = approved_user(update)
    if not user:
        await update.message.reply_text("Du bist nicht freigeschaltet.")
        return
    searches = get_active_searches(user['id'])
    if not searches:
        await update.message.reply_text(NO_SEARCHES)
        return
    text, markup = _stop_list(searches)
    await update.message.reply_text(text, reply_markup=markup)


def _own_active_search(user, data):
    """Liest die Suchen-ID aus den Button-Daten und prüft, ob sie dem Nutzer gehört."""
    try:
        search_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return None
    search = get_search(search_id)
    if not search or search['user_id'] != user['id'] or not search['is_active']:
        return None
    return search


async def on_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = approved_user(update)
    search = _own_active_search(user, query.data) if user else None
    service = SERVICES.get(search['search_type']) if search else None
    if not service:
        await query.answer("Diese Suche ist nicht mehr aktiv.", show_alert=True)
        return
    await query.answer("Einen Moment …")

    target = date.fromisoformat(search['target_date']) if search['target_date'] else None
    view = await current_view(service, search['location'], search['mode'], target)
    if view is None:
        text = "Den aktuellen Stand konnte ich gerade nicht abrufen. Bitte versuche es gleich noch einmal."
    else:
        shown, _, slots_by_day = view
        text = status_text(service, search['location'], search['mode'], target, shown, slots_by_day,
                           "📊 Aktueller Stand")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Jetzt buchen ↗", url=booking_url(service)),
         InlineKeyboardButton("Suche beenden", callback_data=f"stopl:{search['id']}")],
        [InlineKeyboardButton("« Alle Suchen", callback_data="list:status")],
    ])
    await edit_message(query, text, markup)


async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = approved_user(update)
    if not user:
        await query.answer("Du bist nicht freigeschaltet.", show_alert=True)
        return
    await query.answer()
    searches = get_active_searches(user['id'])
    if not searches:
        await edit_message(query, NO_SEARCHES)
        return
    await edit_message(query, *_status_list(searches))


async def on_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """stop:<id> aus Benachrichtigungen, stopl:<id> aus Listen."""
    query = update.callback_query
    user = approved_user(update)
    search = _own_active_search(user, query.data) if user else None
    if not search:
        await query.answer("Diese Suche ist bereits beendet.")
        return
    deactivate_search(search['id'])
    await query.answer("Suche beendet.")

    if query.data.startswith("stopl:"):
        remaining = get_active_searches(user['id'])
        if remaining:
            text, markup = _stop_list(remaining)
            await edit_message(query, f"⏹ Beendet: {search_button_label(search)}\n\n{text}", markup)
        else:
            await edit_message(query, f"⏹ Beendet: {search_button_label(search)}\n\n{NO_SEARCHES}")
    else:
        # Benachrichtigung stehen lassen, nur die Buttons entfernen
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"⏹ Suche beendet: {search_button_label(search)}")


async def on_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = approved_user(update)
    if not user:
        await query.answer("Du bist nicht freigeschaltet.", show_alert=True)
        return
    count = deactivate_all_searches(user['id'])
    await query.answer("Alle Suchen beendet.")
    await edit_message(query, f"⏹ {count} Suche(n) beendet.\nStarte eine neue mit /search.")
