import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# config.py verlangt diese Variablen beim Import
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_ID", "1")

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    import database.db as database
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "test.db"))
    database.init_db()
    return database


@pytest.fixture
def make_user(db):
    from database.models import approve_user, create_user, get_user_by_telegram_id

    def _make(telegram_id, approved=True):
        create_user(telegram_id, "Max", "Muster", "01.01.1990")
        user = get_user_by_telegram_id(telegram_id)
        if approved:
            approve_user(user['id'])
        return get_user_by_telegram_id(telegram_id)
    return _make


# ---------------------------------------------------------------------------
# eTermin-Ersatz
# ---------------------------------------------------------------------------

class FakeAvailability:
    """Ersetzt scrapers.registry.Availability ohne Netz."""

    def __init__(self, days=None, slots=None, fail=()):
        self.days_by_key = days or {}      # {service_key: [date]}
        # {(service_key, date): [Slot]}; ohne Eintrag hat ein Tag ein Zeitfenster um 9 Uhr
        # in einem Kalender ohne Standort, [] heißt: Tag laut Übersicht frei, aber leer
        self.slots_by = slots or {}
        self.fail = set(fail)              # service_keys, die einen Fehler werfen
        self.day_calls = []

    async def days(self, service):
        from scrapers.etermin import EterminError
        await asyncio.sleep(0)  # wie echte Netzwerkabfrage: andere Aufgaben kommen dazwischen
        self.day_calls.append(service.key)
        if service.key in self.fail:
            raise EterminError("kaputt")
        return list(self.days_by_key.get(service.key, []))

    async def slots(self, service, day, location=None):
        from datetime import datetime

        from scrapers.catalog import location_for_calendar
        from scrapers.etermin import Slot
        default = [Slot(datetime(day.year, day.month, day.day, 9, 0), "Kalender")]
        result = self.slots_by.get((service.key, day), default)
        if location:
            result = [s for s in result if location_for_calendar(s.calendar) == location]
        return result

    async def matching_days(self, service, location, days, limit=None):
        from scrapers.registry import Availability
        return await Availability.matching_days(self, service, location, days, limit)


@pytest.fixture
def fake_availability(monkeypatch):
    from scrapers import registry
    fake = FakeAvailability()
    monkeypatch.setattr(registry, "availability", fake)
    return fake


# ---------------------------------------------------------------------------
# Telegram-Ersatz
# ---------------------------------------------------------------------------

class FakeBot:
    def __init__(self):
        self.sent = []          # (chat_id, text, reply_markup)
        self.blocked = set()
        self.failures = {}      # chat_id → Ausnahmen für die nächsten Sendeversuche

    async def send_message(self, chat_id, text, reply_markup=None):
        from telegram.error import Forbidden
        if chat_id in self.blocked:
            raise Forbidden("blocked")
        if self.failures.get(chat_id):
            raise self.failures[chat_id].pop(0)
        self.sent.append((chat_id, text, reply_markup))


class FakeContext:
    def __init__(self, args=(), user_data=None, bot=None):
        self.args = list(args)
        self.user_data = {} if user_data is None else user_data
        self.bot = bot or FakeBot()


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []       # (text, reply_markup)

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))
        return SentMessage(self.replies)


class SentMessage:
    """Vom Bot gesendete Nachricht; Bearbeitungen landen in der Antwortliste."""

    def __init__(self, replies):
        self._replies = replies

    async def edit_text(self, text, reply_markup=None):
        self._replies.append((text, reply_markup))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []         # (text, reply_markup)
        self.markup_removed = False
        self.message = FakeMessage()
        self.too_old = False    # alte Nachricht: Telegram lehnt Bearbeitungen ab

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def edit_message_reply_markup(self, reply_markup=None):
        if self.too_old:
            from telegram.error import BadRequest
            raise BadRequest("Message can't be edited")
        self.markup_removed = reply_markup is None


class FakeUpdate:
    def __init__(self, user_id, text=None, data=None):
        self.effective_user = type("U", (), {"id": user_id})()
        self.effective_chat = type("C", (), {"id": user_id})()  # Privatchat: Chat-ID = Nutzer-ID
        self.message = FakeMessage(text) if text is not None else None
        self.callback_query = FakeQuery(data) if data is not None else None


def callback_datas(markup):
    """Alle callback_data/URLs einer InlineKeyboardMarkup als flache Liste."""
    if markup is None:
        return []
    return [b.callback_data or b.url for row in markup.inline_keyboard for b in row]
