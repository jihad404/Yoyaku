import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Umgebungsvariable {name} fehlt (siehe .env).")
    return value


BOT_TOKEN = _require("BOT_TOKEN")

try:
    ADMIN_ID = int(_require("ADMIN_ID"))
except ValueError:
    raise RuntimeError("ADMIN_ID muss eine numerische Telegram-ID sein.")
