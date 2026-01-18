from telegram.ext import Application, CommandHandler

from config import BOT_TOKEN
from bot.handlers import start, register

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))

    print("Bot startet...")
    app.run_polling()

if __name__ == "__main__":
    main()