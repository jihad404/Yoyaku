import json
import uuid

from database.db import get_connection

def get_user_by_telegram_id(telegram_id):
    """Sucht einen Nutzer anhand seiner Telegram-ID."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'SELECT * FROM users WHERE telegram_id = ?',
        (telegram_id,)
    )

    user = cursor.fetchone()
    connection.close()

    return user

def get_user_by_id(user_id):
    """Sucht einen Nutzer anhand seiner User-ID."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'SELECT * FROM users WHERE id = ?',
        (user_id,)
    )

    user = cursor.fetchone()
    connection.close()

    return user

def create_user(telegram_id, first_name, last_name, birthdate):
    """Erstellt einen neuen Nutzer."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        '''INSERT INTO users (telegram_id, first_name, last_name, birthdate)
        VALUES (?, ?, ?, ?)''',
        (telegram_id, first_name, last_name, birthdate)
    )

    connection.commit()
    connection.close()


def approve_user(user_id):
    """Gibt einen Nutzer frei."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE users SET is_approved = 1 WHERE id = ?',
        (user_id,)
    )

    connection.commit()
    connection.close()


def is_admin(telegram_id):
    """Prüft ob ein Nutzer Admin ist."""
    user = get_user_by_telegram_id(telegram_id)

    if user and user['is_admin'] == 1:
        return True
    return False

def set_admin(telegram_id):
    """Setzt einen Nutzer als Admin und gibt ihn frei."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE users SET is_admin = 1, is_approved = 1 WHERE telegram_id = ?',
        (telegram_id,)
    )
    
    connection.commit()
    connection.close()


def get_pending_users():
    """Holt alle Nutzer die auf Freigabe warten."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'SELECT * FROM users WHERE is_approved = 0 AND is_admin = 0'
    )

    users = cursor.fetchall()
    connection.close()

    return users

MAX_ACTIVE_SEARCHES = 5


def get_active_searches(user_id):
    """Alle aktiven Suchen eines Nutzers, älteste zuerst."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'SELECT * FROM searches WHERE user_id = ? AND is_active = 1 ORDER BY id',
        (user_id,)
    )

    searches = cursor.fetchall()
    connection.close()

    return searches


def get_search(search_id):
    """Holt eine Suche anhand ihrer ID."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute('SELECT * FROM searches WHERE id = ?', (search_id,))

    search = cursor.fetchone()
    connection.close()

    return search


def find_duplicate_search(user_id, service_key, mode, target_date, location):
    """Gibt eine identische aktive Suche zurück, falls vorhanden."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        '''SELECT * FROM searches
        WHERE user_id = ? AND is_active = 1 AND search_type = ? AND mode = ?
          AND target_date IS ? AND location IS ?''',
        (user_id, service_key, mode, target_date, location)
    )

    search = cursor.fetchone()
    connection.close()

    return search


def create_search(user_id, service_key, mode, target_date=None, location=None, state=None):
    """Legt eine Suche an. target_date als YYYY-MM-DD, state als dict."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        '''INSERT INTO searches (user_id, search_type, mode, target_date, location, state)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, service_key, mode, target_date, location, json.dumps(state or {}))
    )

    connection.commit()
    search_id = cursor.lastrowid
    connection.close()

    return search_id


def update_search_state(search_id, state: dict):
    """Speichert den Auswertungszustand einer Suche als JSON."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE searches SET state = ? WHERE id = ?',
        (json.dumps(state), search_id)
    )

    connection.commit()
    connection.close()


def load_state(search) -> dict:
    """Liest den gespeicherten Zustand; kaputte oder fehlende Werte → {}."""
    try:
        state = json.loads(search['state'] or '{}')
    except (TypeError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def deactivate_search(search_id):
    """Deaktiviert eine Suche."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE searches SET is_active = 0 WHERE id = ?',
        (search_id,)
    )

    connection.commit()
    connection.close()


def deactivate_all_searches(user_id):
    """Beendet alle aktiven Suchen eines Nutzers und gibt die Anzahl zurück."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE searches SET is_active = 0 WHERE user_id = ? AND is_active = 1',
        (user_id,)
    )

    connection.commit()
    count = cursor.rowcount
    connection.close()

    return count


def get_all_active_searches():
    """Gibt alle aktiven Suchen zurück (inkl. Telegram-ID des Nutzers)."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute('''
        SELECT s.*, u.telegram_id
        FROM searches s
        JOIN users u ON s.user_id = u.id
        WHERE s.is_active = 1
    ''')

    searches = cursor.fetchall()
    connection.close()

    return searches


def get_service_snapshot(webid) -> dict:
    """Zuletzt gesehener Stand der Dienstleistungen einer Buchungsseite: {sid: Row}."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute('SELECT * FROM etermin_services WHERE webid = ?', (webid,))

    rows = {row['sid']: row for row in cursor.fetchall()}
    connection.close()

    return rows


def save_service_snapshot(webid, services):
    """Ersetzt den gespeicherten Stand einer Buchungsseite (Liste aus etermin.list_services)."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute('DELETE FROM etermin_services WHERE webid = ?', (webid,))
    cursor.executemany(
        'INSERT INTO etermin_services (webid, sid, name, no_booking, description) VALUES (?, ?, ?, ?, ?)',
        [(webid, s['sid'], s['name'], int(s['no_booking']), s['description']) for s in services]
    )

    connection.commit()
    connection.close()


def log_error(error_message, user_id=None):
    """Speichert einen Fehler und gibt eine kurze Referenz für den Nutzer zurück."""
    reference = uuid.uuid4().hex[:8].upper()
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'INSERT INTO error_logs (reference, user_id, error_message) VALUES (?, ?, ?)',
        (reference, user_id, error_message)
    )

    connection.commit()
    connection.close()

    return reference
