import sqlite3
import os

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

    # Migration: target_date nachrüsten falls Tabelle schon existiert
    try:
        cursor.execute('ALTER TABLE searches ADD COLUMN target_date TEXT')
    except Exception:
        pass
    
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