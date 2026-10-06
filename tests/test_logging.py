import asyncio
import logging

import pytest
from telegram.error import BadRequest

from bot import errors
from conftest import FakeContext, FakeUpdate
from logging_setup import setup_logging


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for h in root.handlers:
        h.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_setup_writes_file_and_silences_httpx(tmp_path, restore_logging):
    setup_logging(str(tmp_path))
    logging.getLogger("manager.checker").info("Prüfrunde: Test")
    logging.getLogger("httpx").info("GET https://api.telegram.org/bot<TOKEN>/getUpdates")
    for h in logging.getLogger().handlers:
        h.flush()

    content = (tmp_path / "yoyaku.log").read_text(encoding="utf-8")
    assert "INFO    manager.checker: Prüfrunde: Test" in content
    assert "getUpdates" not in content


class _Ctx(FakeContext):
    def __init__(self, error):
        super().__init__()
        self.error = error


def _update_with_chat(user_id, data):
    update = FakeUpdate(user_id, data=data)
    update.effective_chat = type("C", (), {"id": user_id})()
    return update


@pytest.fixture(autouse=True)
def reset_alert():
    errors._last_admin_alert = 0.0


def test_error_handler_logs_stores_and_alerts(make_user, caplog):
    user = make_user(100)
    ctx = _Ctx(ValueError("kaputt"))
    with caplog.at_level(logging.ERROR, logger="bot.errors"):
        asyncio.run(errors.on_error(_update_with_chat(100, "svc:reisepass"), ctx))

    assert "Button 'svc:reisepass'" in caplog.text and f"Nutzer {user['id']}" in caplog.text
    assert "Max" not in caplog.text and "Muster" not in caplog.text   # keine Namen im Log
    to_user = [t for c, t, _ in ctx.bot.sent if c == 100]
    to_admin = [t for c, t, _ in ctx.bot.sent if c == 1]
    assert "Fehlerreferenz" in to_user[0]
    assert "ValueError" in to_admin[0]

    from database.db import get_connection
    row = get_connection().execute("SELECT * FROM error_logs").fetchone()
    assert row['user_id'] == user['id'] and "kaputt" in row['error_message']


def test_admin_alert_rate_limited(make_user):
    make_user(100)
    ctx = _Ctx(ValueError("kaputt"))
    for _ in range(3):
        asyncio.run(errors.on_error(_update_with_chat(100, "svc:reisepass"), ctx))
    assert len([c for c, _, _ in ctx.bot.sent if c == 1]) == 1


def test_harmless_errors_are_ignored(make_user):
    ctx = _Ctx(BadRequest("Query is too old and response timeout expired or query id is invalid"))
    asyncio.run(errors.on_error(_update_with_chat(100, "svc:reisepass"), ctx))
    assert ctx.bot.sent == []
