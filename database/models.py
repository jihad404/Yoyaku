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