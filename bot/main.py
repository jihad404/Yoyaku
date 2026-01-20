from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN
from bot.handlers import start, register, pending, approve

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(MessageHandler(filters.Regex(r'^/approve_\d+$'), approve))
    print("Bot startet...")
    app.run_polling()

if __name__ == "__main__":
    main()