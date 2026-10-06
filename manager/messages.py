"""Texte für Benachrichtigungen und Statusanzeigen (reine Funktionen)."""
from collections import OrderedDict
from datetime import date

from scrapers.catalog import LOCATIONS, SITES, Service, location_for_calendar, service_label

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MAX_TIMES = 3


def format_day(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m.}"


def mode_label(mode: str, target: date | None) -> str:
    if mode == "until":
        return f"bis spätestens {target:%d.%m.%Y}"
    if mode == "day":
        return f"am {target:%d.%m.%Y}"
    return "so früh wie möglich"


def _times(slots) -> str:
    # Mehrere Schalter liefern dieselbe Uhrzeit mehrfach → nur einmal anzeigen
    times = list(dict.fromkeys(f"{s.start:%H:%M}" for s in slots))
    text = ", ".join(times[:MAX_TIMES])
    if len(times) > MAX_TIMES:
        text += f" (+{len(times) - MAX_TIMES} weitere)"
    return text


def format_slots(service: Service, location: str | None, slots) -> str:
    """Uhrzeiten eines Tages. Beim Bürgerservice ohne Standortfilter nach Station gruppiert."""
    if not slots:
        return ""
    if location or not SITES[service.site].has_locations:
        return _times(slots)
    by_location = OrderedDict()
    for s in slots:
        key = location_for_calendar(s.calendar)
        by_location.setdefault(LOCATIONS.get(key, "Sonstige"), []).append(s)
    parts = [f"{name} {_times(group)}" for name, group in list(by_location.items())[:3]]
    if len(by_location) > 3:
        parts.append(f"+{len(by_location) - 3} weitere Standorte")
    return " · ".join(parts)


def day_lines(service: Service, location: str | None, days: list[date], slots_by_day: dict) -> list[str]:
    lines = []
    for day in days:
        times = format_slots(service, location, slots_by_day.get(day, []))
        lines.append(f"📅 {format_day(day)}" + (f"  {times}" if times else ""))
    return lines


def notification_text(service: Service, location: str | None, decision, target: date | None,
                      slots_by_day: dict) -> str:
    label = service_label(service, location)
    if decision.kind == "earlier":
        head = "🔔 Früherer Termin frei!" if decision.previous else "🔔 Termin frei!"
        lines = [head, label, "", *day_lines(service, location, decision.days, slots_by_day)]
        if decision.previous:
            lines.append(f"   vorher frühester: {format_day(decision.previous)}")
        return "\n".join(lines)
    if decision.kind == "new_days":
        head = f"🔔 Neue Termine bis {target:%d.%m.}!"
        return "\n".join([head, label, "", *day_lines(service, location, decision.days, slots_by_day)])
    if decision.kind == "day_available":
        return "\n".join(["🎯 Dein Wunschtag ist frei!", label, "",
                          *day_lines(service, location, decision.days, slots_by_day)])
    if decision.kind == "day_gone":
        return "\n".join(["😕 Wunschtag nicht mehr verfügbar", label, "",
                          f"Am {format_day(target)} ist leider nichts mehr frei. Die Suche läuft weiter."])
    if decision.kind == "expired":
        return "\n".join(["⏹ Suche beendet", label, "",
                          f"Das Datum {target:%d.%m.%Y} ist vorbei. Starte eine neue Suche mit /search."])
    raise ValueError(decision.kind)


def status_text(service: Service, location: str | None, mode: str, target: date | None,
                days: list[date], slots_by_day: dict, title: str) -> str:
    lines = [title, service_label(service, location), f"Modus: {mode_label(mode, target)}", ""]
    if days:
        lines.append("Nächste freie Tage:")
        lines += day_lines(service, location, days, slots_by_day)
    else:
        lines.append("Aktuell keine freien Termine – ich melde mich, sobald sich das ändert.")
    return "\n".join(lines)
