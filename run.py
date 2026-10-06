import logging

from logging_setup import setup_logging

if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger("yoyaku")

    from bot.main import main
    from database.db import init_db

    logger.info("Initialisiere Datenbank...")
    init_db()
    logger.info("Datenbank bereit.")
    main()
