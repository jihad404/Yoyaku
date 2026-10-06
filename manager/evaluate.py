"""Auswertung einer Suche: reine Funktionen ohne Netz, Datenbank oder Telegram.

Eingabe sind die *passenden* freien Tage (bereits nach Standort gefiltert),
Ausgabe ist eine Entscheidung, ob und worüber benachrichtigt wird, plus der
neue Zustand, der in ``searches.state`` gespeichert wird.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

MODES = ("earliest", "until", "day")

# Derselbe Tag wird pro Suche höchstens so oft gemeldet
REPEAT_WINDOW_SECONDS = 2 * 60 * 60


@dataclass
class Decision:
    kind: str | None  # earlier | new_days | day_available | day_gone | expired | None
    state: dict
    days: list = field(default_factory=list)
    previous: date | None = None
    end: bool = False


def _iso(day: date) -> str:
    return day.isoformat()


def _relevant(mode: str, target: date | None, days: list[date], today: date) -> list[date]:
    days = sorted(d for d in days if d >= today)
    if mode == "until":
        return [d for d in days if d <= target]
    return days


def initial_state(mode: str, target: date | None, days: list[date], now: datetime) -> dict:
    """Zustand direkt nach dem Anlegen; der Nutzer hat den aktuellen Stand
    bereits gesehen, daher gelten die angezeigten Tage als gemeldet."""
    relevant = _relevant(mode, target, days, now.date())
    ts = now.timestamp()
    state = {"initialized": True, "notified": {}}
    if mode == "earliest":
        state["earliest"] = _iso(relevant[0]) if relevant else None
        if relevant:
            state["notified"][_iso(relevant[0])] = ts
    elif mode == "until":
        state["known"] = [_iso(d) for d in relevant]
        state["notified"] = {_iso(d): ts for d in relevant}
    else:
        available = target in days
        state["day_available"] = available
        if available:
            state["notified"][_iso(target)] = ts
    return state


def evaluate(mode: str, target: date | None, state: dict, days: list[date], now: datetime) -> Decision:
    today = now.date()
    ts = now.timestamp()

    if mode in ("until", "day") and target < today:
        return Decision("expired", dict(state), end=True)

    notified = {k: v for k, v in (state.get("notified") or {}).items() if k >= _iso(today)}
    new_state = {**state, "initialized": True, "notified": notified}

    def recent(day: date) -> bool:
        return ts - notified.get(_iso(day), 0) < REPEAT_WINDOW_SECONDS

    def mark(day: date):
        notified[_iso(day)] = ts

    relevant = _relevant(mode, target, days, today)
    first_run = not state.get("initialized")

    if mode == "earliest":
        current = relevant[0] if relevant else None
        previous = None if first_run or not state.get("earliest") else date.fromisoformat(state["earliest"])
        new_state["earliest"] = _iso(current) if current else None
        if current and (previous is None or current < previous) and not recent(current):
            mark(current)
            return Decision("earlier", new_state, [current], previous=previous)
        return Decision(None, new_state)

    if mode == "until":
        known = set() if first_run else set(state.get("known") or [])
        new_state["known"] = [_iso(d) for d in relevant]
        new_days = [d for d in relevant if _iso(d) not in known and not recent(d)]
        for d in new_days:
            mark(d)
        return Decision("new_days" if new_days else None, new_state, new_days)

    # mode == "day": day_available = was der Nutzer zuletzt mitgeteilt bekam
    available = target in days
    was_available = bool(state.get("day_available")) and not first_run
    new_state["day_available"] = was_available
    if available and not was_available:
        if recent(target):  # gerade erst gemeldet und wieder weg gewesen → noch still bleiben
            return Decision(None, new_state)
        mark(target)
        new_state["day_available"] = True
        return Decision("day_available", new_state, [target])
    if not available and was_available:
        new_state["day_available"] = False
        return Decision("day_gone", new_state, [target])
    return Decision(None, new_state)
