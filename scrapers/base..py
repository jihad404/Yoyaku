import asyncio
import argparse
from telegram import Bot
from config import BOT_TOKEN
from database.models import get_user_by_id

async def send_notification (user_id, message):
    """Sendet eine Telegram Nachricht an den Nutzer."""
    bot = Bot(token=BOT_TOKEN)
    user = get_user_by_id(user_id)

    if user:
        await bot.send_message(chat_id=user['telegram_id'], text=message)

def parse_args():
    """Liest die Kommandozeilen-Argumente."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', type=int, required=True)
    parser.add_argument('--search', type=int, required=True)
    return parser.parse_args()

