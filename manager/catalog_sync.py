"""Täglicher Abgleich des Katalogs mit den Dienstleistungen auf eTermin.

Gemeldet werden an den Admin:
- ➕/➖ neue oder verschwundene Dienstleistungen,
- 🚫 Katalog-Dienstleistungen, die eTermin zwar noch listet, die dort aber nicht
  mehr gebucht werden können (z. B. "ausschließlich im Bürgerservice"),
- ✏️ jede Änderung an Name, Hinweistext oder Terminwahl seit dem letzten Abgleich.

Nutzer mit aktiven Suchen auf verschwundene oder nicht mehr buchbare
Dienstleistungen bekommen einmal einen Hinweis.
"""
import difflib
import logging
import re

from config import ADMIN_ID
from database.models import (
    get_all_active_searches, get_service_snapshot, load_state, log_error, save_service_snapshot,
    update_search_state,
)
from manager.checker import send_to_user
from scrapers import etermin
from scrapers.catalog import SERVICES, SITES, known_sids, service_by_sid, service_label

logger = logging.getLogger(__name__)

GONE_TEXT = "Diese Dienstleistung wird auf der Buchungsseite derzeit nicht mehr angeboten."
NO_BOOKING_TEXT = "Die Buchungsseite bietet für diese Dienstleistung keine Terminwahl mehr an."

# Formulierungen, mit denen eTermin-Seiten auf eine andere zuständige Stelle verweisen.
# Nicht: "Tipp: Dies können Sie auch im Bürgerservice erledigen" (dort weiter buchbar).
_ELSEWHERE = re.compile(
    r"ausschlie(?:ß|ss)lich (?:im|in der|beim|bei der|bei|über)\b"
    r"|nur noch (?:im|in der|beim|bei der|bei|über)\b"
    r"|nicht mehr (?:online )?(?:buchbar|möglich|angeboten|hier)",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"\n|(?<=[.!?])\s+")
MAX_QUOTE = 200


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def _quote(sentence: str) -> str:
    return sentence if len(sentence) <= MAX_QUOTE else sentence[:MAX_QUOTE - 1] + "…"


def _added_text(old: str, new: str) -> list[str]:
    """Neu hinzugekommene Textstellen (wortweiser Vergleich), höchstens zwei."""
    a, b = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [_quote(" ".join(b[j1:j2])) for op, _, _, j1, j2 in matcher.get_opcodes()
            if op in ("insert", "replace")][:2]


def booking_elsewhere(entry: dict) -> str | None:
    """Grund, warum eine von eTermin gelistete Dienstleistung dort nicht buchbar ist, sonst None."""
    for sentence in _sentences(entry["description"]):
        if _ELSEWHERE.search(sentence):
            return _quote(sentence)
    if entry["no_booking"]:
        return NO_BOOKING_TEXT
    return None


def _changes(site, previous: dict, live_by_sid: dict) -> list[str]:
    """Änderungen gegenüber dem letzten Abgleich. Ohne gespeicherten Stand: keine."""
    lines = []
    for sid, entry in sorted(live_by_sid.items()):
        old = previous.get(sid)
        if old is None:
            continue
        name = entry["name"]
        if old["name"] != name:
            lines.append(f"✏️ {site.name}: „{old['name']}“ (ID {sid}) heißt jetzt „{name}“")
        if bool(old["no_booking"]) != entry["no_booking"]:
            what = "bietet keine Terminwahl mehr an" if entry["no_booking"] else "bietet wieder eine Terminwahl an"
            lines.append(f"✏️ {site.name}: „{name}“ (ID {sid}) {what}")
        if old["description"] != entry["description"]:
            added = _added_text(old["description"], entry["description"])
            detail = " … ".join(f"„{s}“" for s in added) if added else "(Text gekürzt)"
            lines.append(f"✏️ {site.name}: Hinweistext zu „{name}“ (ID {sid}) geändert: {detail}")
    return lines


async def compare_catalog(client) -> tuple[list[str], dict[str, str]]:
    """Gibt Meldungszeilen für den Admin und die betroffenen Katalog-Schlüssel
    (mit Hinweistext für die Nutzer) zurück."""
    lines, affected = [], {}
    for site in SITES.values():
        try:
            live = await etermin.list_services(client, site.webid)
        except etermin.EterminError as e:
            log_error(f"Katalogabgleich {site.webid}: {e}")
            lines.append(f"⚠️ {site.name}: Abfrage fehlgeschlagen")
            continue

        live_by_sid = {s["sid"]: s for s in live}
        known = known_sids(site.key)
        for sid in sorted(live_by_sid.keys() - known):
            entry = live_by_sid[sid]
            lines.append(f"➕ {site.name}: {entry['name']} (Gruppe „{entry['group']}“, ID {sid})")
        for sid in sorted(known - live_by_sid.keys()):
            service = service_by_sid(site.key, sid)
            if service:
                affected[service.key] = GONE_TEXT
                lines.append(f"➖ {site.name}: {service.name} (ID {sid}) gibt es nicht mehr")
            else:
                lines.append(f"➖ {site.name}: ID {sid} (Alias oder umgezogen) gibt es nicht mehr")

        for sid, entry in sorted(live_by_sid.items()):
            service = service_by_sid(site.key, sid)  # umgezogene sind bereits erledigt → None
            reason = booking_elsewhere(entry)
            if service and reason:
                affected[service.key] = reason
                lines.append(f"🚫 {site.name}: {service.name} (ID {sid}) ist dort nicht mehr buchbar: „{reason}“")

        lines += _changes(site, get_service_snapshot(site.webid), live_by_sid)
        save_service_snapshot(site.webid, live)
    return lines, affected


def _user_notice(search, reason: str) -> str:
    service = SERVICES[search['search_type']]
    if reason == GONE_TEXT:
        detail = reason
    else:
        detail = f"Laut Buchungsseite kann diese Dienstleistung dort nicht mehr gebucht werden:\n„{reason}“"
    return ("⚠️ Hinweis zu deiner Suche\n"
            f"{service_label(service, search['location'])}\n\n"
            f"{detail}\n\n"
            "Deine Suche bleibt vorerst aktiv; beende sie bei Bedarf mit /stop. "
            "Der Admin ist informiert.")


async def sync_catalog(context, client_factory=etermin.make_client) -> None:
    """PTB-JobQueue-Funktion."""
    async with client_factory() as client:
        lines, affected = await compare_catalog(client)

    if not lines:
        logger.info("Katalogabgleich: keine Abweichungen")
    else:
        logger.warning("Katalogabgleich: %s Abweichung(en): %s", len(lines), "; ".join(lines))
        hint = "Bitte prüfen und ggf. scrapers/catalog.py anpassen"
        if any(line.startswith("🚫") for line in lines):
            hint += " (umgezogene Dienstleistungen in MOVED eintragen)"
        text = "📋 Katalogabgleich mit eTermin:\n\n" + "\n".join(lines) + f"\n\n{hint}."
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=text[:4000])
        except Exception as e:
            log_error(f"Katalogabgleich: Admin-Nachricht fehlgeschlagen: {e}")

    for search in get_all_active_searches():
        reason = affected.get(search['search_type'])
        if reason is None:
            continue
        state = load_state(search)
        if state.get("gone_notified"):
            continue
        await send_to_user(context, search, _user_notice(search, reason))
        update_search_state(search['id'], {**state, "gone_notified": True})
