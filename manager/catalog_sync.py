"""Täglicher Abgleich des Katalogs mit den Dienstleistungen auf eTermin."""
from config import ADMIN_ID
from database.models import get_all_active_searches, load_state, log_error, update_search_state
from manager.checker import send_to_user
from scrapers import etermin
from scrapers.catalog import SERVICES, SITES, known_sids, service_label


async def compare_catalog(client) -> tuple[list[str], set[str]]:
    """Gibt Meldungszeilen für den Admin und die Schlüssel verschwundener Dienstleistungen zurück."""
    lines, gone_keys = [], set()
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
            service = next((s for s in SERVICES.values() if s.site == site.key and s.sid == sid), None)
            if service:
                gone_keys.add(service.key)
                lines.append(f"➖ {site.name}: {service.name} (ID {sid}) gibt es nicht mehr")
            else:
                lines.append(f"➖ {site.name}: Alias-ID {sid} gibt es nicht mehr")
    return lines, gone_keys


async def sync_catalog(context, client_factory=etermin.make_client) -> None:
    """PTB-JobQueue-Funktion."""
    async with client_factory() as client:
        lines, gone_keys = await compare_catalog(client)

    if lines:
        text = "📋 Katalogabgleich mit eTermin:\n\n" + "\n".join(lines) + \
               "\n\nBitte scrapers/catalog.py anpassen."
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=text[:4000])
        except Exception as e:
            log_error(f"Katalogabgleich: Admin-Nachricht fehlgeschlagen: {e}")

    for search in get_all_active_searches():
        if search['search_type'] not in gone_keys:
            continue
        state = load_state(search)
        if state.get("gone_notified"):
            continue
        service = SERVICES[search['search_type']]
        await send_to_user(context, search, (
            "⚠️ Hinweis zu deiner Suche\n"
            f"{service_label(service, search['location'])}\n\n"
            "Diese Dienstleistung wird auf der Buchungsseite derzeit nicht mehr angeboten. "
            "Deine Suche bleibt aktiv; beende sie bei Bedarf mit /stop."
        ))
        update_search_state(search['id'], {**state, "gone_notified": True})
