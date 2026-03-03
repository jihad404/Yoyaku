from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN
from bot.handlers import (
    start, register, pending, approve,
    search, select_category, search_any, search_date,
    stop, status
)
from manager.checker import check_and_notify, CHECK_INTERVAL


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(MessageHandler(filters.Regex(r'^/approve_\d+$'), approve))

    app.add_handler(CommandHandler("search", search))
    app.add_handler(MessageHandler(filters.Regex(r'^/search_\d+$'), select_category))
    app.add_handler(CommandHandler("search_any", search_any))
    app.add_handler(CommandHandler("search_date", search_date))

    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))

    app.job_queue.run_repeating(check_and_notify, interval=CHECK_INTERVAL, first=30)

    print("Bot startet...")
    app.run_polling()


if __name__ == "__main__":
    main()
