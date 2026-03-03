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

def get_active_search(user_id):
    """Holt die aktive Suche eines Nutzers."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'SELECT * FROM searches WHERE user_id = ? AND is_active = 1',
        (user_id,)
    )

    search = cursor.fetchone()
    connection.close()

    return search

def create_search(user_id, search_type, target_date=None):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'INSERT INTO searches (user_id, search_type, target_date) VALUES (?, ?, ?)',
        (user_id, search_type, target_date)
    )

    connection.commit()
    search_id = cursor.lastrowid
    connection.close()

    return search_id


def set_search_target_date(search_id, target_date):
    """Setzt das Wunschdatum einer Suche (YYYY-MM-DD)."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE searches SET target_date = ? WHERE id = ?',
        (target_date, search_id)
    )

    connection.commit()
    connection.close()


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


def get_all_active_searches():
    """Gibt alle aktiven Suchen zurück (inkl. Nutzerdaten)."""
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


def update_last_known_dates(search_id, dates: list):
    """Speichert die zuletzt bekannten verfügbaren Termine als JSON."""
    import json
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        'UPDATE searches SET last_known_dates = ? WHERE id = ?',
        (json.dumps(dates), search_id)
    )

    connection.commit()
    connection.close()
