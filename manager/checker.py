import asyncio
import json
from datetime import date, datetime

from database.models import get_all_active_searches, deactivate_search, update_last_known_dates
from bot.handlers import _run_scraper, SEARCH_CATEGORIES

# Intervall in Sekunden (alle 5 Minuten prüfen)
CHECK_INTERVAL = 300


def _format_date(date_str: str) -> str:
    """YYYY-MM-DD → TT.MM.JJJJ"""
    return datetime.fromisoformat(date_str).strftime("%d.%m.%Y")


async def check_and_notify(context):
    """
    PTB JobQueue-Funktion: Prüft alle aktiven Suchen auf Änderungen
    und benachrichtigt Nutzer bei neuen oder weggefallenen Terminen.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checker läuft...")

    searches = get_all_active_searches()

    if not searches:
        print("  Keine aktiven Suchen.")
        return

    print(f"  {len(searches)} aktive Suche(n) gefunden.")

    for search in searches:
        search_id = search['id']
        telegram_id = search['telegram_id']
        scraper_name = search['search_type']
        target_str = search['target_date']

        # Metadaten für Benachrichtigungen
        type_info = next((c for c in SEARCH_CATEGORIES.values() if c["scraper"] == scraper_name), None)
        service_name = type_info["service_name"] if type_info else scraper_name
        category_name = type_info["name"] if type_info else ""

        # Wunschdatum in der Vergangenheit → Suche beenden
        if target_str:
            try:
                target_date = date.fromisoformat(target_str)
            except ValueError:
                continue

            if target_date < date.today():
                deactivate_search(search_id)
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"Suche beendet.\n\n"
                        f"Dein Wunschtermin am {_format_date(target_str)} "
                        f"liegt inzwischen in der Vergangenheit.\n"
                        "Starte eine neue Suche mit /search."
                    )
                )
                continue

        # Scraper aufrufen
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _run_scraper, scraper_name
            )
        except Exception as e:
            print(f"  Scraper-Fehler für Suche {search_id}: {e}")
            continue

        current_dates = set(result["available_dates"])

        # Zuletzt bekannte Termine laden
        try:
            last_known = set(json.loads(search['last_known_dates'])) if search['last_known_dates'] else None
        except (TypeError, json.JSONDecodeError):
            last_known = None

        # Erste Prüfung: einfach speichern, keine Benachrichtigung
        if last_known is None:
            update_last_known_dates(search_id, sorted(current_dates))
            continue

        new_dates = current_dates - last_known
        removed_dates = last_known - current_dates

        # Keine Änderung → nichts tun
        if not new_dates and not removed_dates:
            continue

        # Geänderte Termine speichern
        update_last_known_dates(search_id, sorted(current_dates))

        # Benachrichtigung zusammenbauen
        if target_str:
            # Wunschdatum-Suche: nur über den gewünschten Tag berichten
            await _notify_target_date(
                context, telegram_id, target_str,
                new_dates, removed_dates,
                service_name, category_name
            )
        else:
            # Allgemeine Suche: alle Änderungen melden
            await _notify_general(
                context, telegram_id,
                new_dates, removed_dates,
                service_name, category_name
            )


async def _notify_target_date(context, telegram_id, target_str,
                               new_dates, removed_dates, service_name, category_name):
    """Benachrichtigt bei Änderungen am Wunschdatum."""
    if target_str in new_dates:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"Termin verfügbar!\n\n"
                f"Behörde: {category_name}\n"
                f"Dienstleistung: {service_name}\n"
                f"Datum: {_format_date(target_str)}\n\n"
                "Jetzt buchen: https://www.etermin.net/stadt-duisburg-zul\n\n"
                "Die Suche läuft weiter und meldet erneut falls sich etwas ändert."
            )
        )
    elif target_str in removed_dates:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                f"Termin nicht mehr verfügbar.\n\n"
                f"Dein Wunschtermin am {_format_date(target_str)} "
                f"ist leider nicht mehr buchbar.\n"
                "Die Suche läuft weiter."
            )
        )


async def _notify_general(context, telegram_id,
                           new_dates, removed_dates, service_name, category_name):
    """Benachrichtigt über alle Terminänderungen."""
    lines = [f"Terminänderung — {service_name}:\n"]

    if new_dates:
        lines.append("Neu verfügbar:")
        for d in sorted(new_dates):
            lines.append(f"  + {_format_date(d)}")

    if removed_dates:
        if new_dates:
            lines.append("")
        lines.append("Nicht mehr verfügbar:")
        for d in sorted(removed_dates):
            lines.append(f"  - {_format_date(d)}")

    await context.bot.send_message(
        chat_id=telegram_id,
        text="\n".join(lines)
    )
