import json
import sqlite3
import os

from scrapers.catalog import MOVED

DATABASE_PATH = os.path.join(os.path.dirname(__file__),'..', 'yoyaku.db')

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    connection = get_connection()
    cursor = connection.cursor()

    # USER Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               telegram_id INTEGER UNIQUE NOT NULL,
               first_name TEXT NOT NULL,
               last_name TEXT NOT NULL,
               birthdate TEXT NOT NULL,
               is_approved INTEGER DEFAULT 0,
               is_admin INTEGER DEFAULT 0,
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Searches Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            search_type TEXT NOT NULL,
            target_date TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Migrationen: Spalten nachrüsten falls Tabelle schon existiert
    try:
        cursor.execute('ALTER TABLE searches ADD COLUMN target_date TEXT')
    except Exception:
        pass
    try:
        cursor.execute('ALTER TABLE searches ADD COLUMN last_known_dates TEXT')
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE searches ADD COLUMN mode TEXT NOT NULL DEFAULT 'earliest'")
        # Einmalig beim Hinzufügen: alte Suchen mit Wunschdatum → Modus "day"
        cursor.execute("UPDATE searches SET mode = 'day' WHERE target_date IS NOT NULL")
    except Exception:
        pass
    try:
        cursor.execute('ALTER TABLE searches ADD COLUMN location TEXT')
    except Exception:
        pass
    try:
        cursor.execute('ALTER TABLE searches ADD COLUMN state TEXT')
    except Exception:
        pass

    # Alte Scraper-Namen auf Katalog-Schlüssel umstellen
    cursor.execute("UPDATE searches SET search_type = 'wiederzulassung' WHERE search_type = 'duisburg_zulassung'")
    cursor.execute("UPDATE searches SET is_active = 0 WHERE search_type = 'duisburg_aufenthalt'")

    # Umgezogene Dienstleistungen (scrapers/catalog.py: MOVED): aktive Suchen umstellen.
    # Der Zustand beginnt neu; "moved_from" sorgt für eine einmalige Nachricht an den Nutzer.
    for moved in MOVED.values():
        cursor.execute(
            "UPDATE searches SET search_type = ?, state = ? WHERE search_type = ? AND is_active = 1",
            (moved.new_key, json.dumps({"moved_from": moved.old_key}), moved.old_key))
    # Durch die Umstellung können identische Suchen entstehen → nur die älteste bleibt aktiv
    cursor.execute('''
        UPDATE searches SET is_active = 0
        WHERE is_active = 1 AND id NOT IN (
            SELECT MIN(id) FROM searches WHERE is_active = 1
            GROUP BY user_id, search_type, mode, IFNULL(target_date, ''), IFNULL(location, '')
        )
    ''')

    # Zuletzt gesehener Stand der eTermin-Dienstleistungen (für den Katalogabgleich)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS etermin_services (
            webid TEXT NOT NULL,
            sid INTEGER NOT NULL,
            name TEXT NOT NULL,
            no_booking INTEGER NOT NULL,
            description TEXT NOT NULL,
            PRIMARY KEY (webid, sid)
        )
    ''')

    # Error Logs Tabelle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            error_message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    connection.commit()
    connection.close()