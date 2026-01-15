from bot.main import main
from database.db import init_db

if __name__ == "__main__":
    print("Initialisiere Datenbank...")
    init_db()
    print("Datenbank bereit.")
    main()