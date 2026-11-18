"""Katalog aller Duisburger eTermin-Dienstleistungen.

Reine Datenpflege: Themen, Buchungsseiten, Standorte und Dienstleistungen.
Bei Änderungen auf eTermin meldet der tägliche Katalogabgleich
(manager/catalog_sync.py) die Abweichungen an den Admin.
"""
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Buchungsseiten
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Site:
    key: str
    webid: str
    name: str
    has_locations: bool = False


SITES = {
    "buergerservice": Site("buergerservice", "stadt-duisburg", "Bürgerservice", has_locations=True),
    "gewerbe": Site("gewerbe", "stadt-duisburg-gewerbe", "Gewerbemeldestelle"),
    "zulassung": Site("zulassung", "stadt-duisburg-zul", "Zulassungsstelle"),
    "fahrerlaubnis": Site("fahrerlaubnis", "qterminstadtduisburgstva", "Fahrerlaubnisbehörde"),
}

# Bürger-Service-Stationen; eTermin führt jede unter mehreren Kalendern
# ("Bürger-Service-Station-Hamborn_Slot2", …)
LOCATIONS = {
    "hamborn": "Hamborn",
    "homberg": "Homberg/Ruhrort/Baerl",
    "meiderich": "Meiderich/Beeck",
    "mitte": "Mitte",
    "rheinhausen": "Rheinhausen",
    "sued": "Süd",
    "walsum": "Walsum",
}

_CALENDAR_PREFIX = "Bürger-Service-Station-"
_LOCATION_BY_LABEL = {label: key for key, label in LOCATIONS.items()}


def location_for_calendar(calendar_name: str) -> str | None:
    """'Bürger-Service-Station-Hamborn_Slot2' → 'hamborn'."""
    if not calendar_name.startswith(_CALENDAR_PREFIX):
        return None
    label = re.sub(r"_Slot\s*\d+$", "", calendar_name[len(_CALENDAR_PREFIX):]).strip()
    return _LOCATION_BY_LABEL.get(label)


# ---------------------------------------------------------------------------
# Themen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    subtopics: dict = field(default_factory=dict)  # key → label, in Anzeigereihenfolge


TOPICS = {t.key: t for t in [
    Topic("ausweis", "🪪 Ausweis & Pass"),
    Topic("wohnen", "🏠 Wohnen & Melden"),
    Topic("fahrzeug", "🚗 Fahrzeug & Zulassung", {
        "zulassung": "Zulassung",
        "kennzeichen": "Kennzeichen",
        "papiere": "Papiere & Umschreibung",
        "verlust": "Diebstahl & Verlust",
        "technik": "Technik",
        "abmeldung": "Abmeldung",
    }),
    Topic("fuehrerschein", "🚦 Führerschein", {
        "antrag": "Beantragen",
        "umtausch": "Umtausch & Ersatz",
        "international": "Internationaler Führerschein",
        "beruf": "Beruf & Personenbeförderung",
        "abholung": "Abholung & Versand",
        "sonstiges": "Sonstiges",
    }),
    Topic("gewerbe", "💼 Gewerbe"),
    Topic("fundsachen", "📦 Fundsachen"),
    Topic("sonstiges", "📄 Bescheinigungen & Sonstiges"),
]}


# ---------------------------------------------------------------------------
# Dienstleistungen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    key: str
    topic: str
    subtopic: str | None
    name: str
    site: str
    sid: int
    keywords: tuple = ()
    aliases: tuple = ()  # weitere eTermin-IDs mit identischer Dienstleistung


def _s(key, topic, subtopic, name, site, sid, keywords="", aliases=()):
    return Service(key, topic, subtopic, name, site, sid, tuple(keywords.split()), tuple(aliases))


_SERVICES = [
    # --- Ausweis & Pass (Bürgerservice) ---
    _s("personalausweis", "ausweis", None, "Personalausweis beantragen", "buergerservice", 90152,
       "perso ausweis id-karte neu verlängern"),
    _s("reisepass", "ausweis", None, "Reisepass beantragen", "buergerservice", 90153,
       "pass reise urlaub verlängern"),
    _s("ausweis_vorlaeufig", "ausweis", None, "Vorläufiger Ausweis / Reisepass", "buergerservice", 90491,
       "notfall vorläufig schnell personalausweis reisepass"),
    _s("ausweis_abholung", "ausweis", None, "Ausweis / Pass abholen", "buergerservice", 93352,
       "abholung abholen personalausweis reisepass eid"),
    _s("eid_karte", "ausweis", None, "eID-Karte beantragen (EU-Bürger)", "buergerservice", 194814,
       "eid ausweiskarte eu unionsbürger"),
    _s("ausweis_pin", "ausweis", None, "PIN für Personalausweis aktivieren", "buergerservice", 194823,
       "pin online-ausweis onlineausweis eid aktivierung personalausweis"),

    # --- Wohnen & Melden (Bürgerservice) ---
    _s("anmeldung", "wohnen", None, "Wohnsitz anmelden (Zuzug)", "buergerservice", 90492,
       "anmeldung anmelden zuzug umzug wohnung meldeadresse neu"),
    _s("abmeldung_wohnsitz", "wohnen", None, "Wohnsitz abmelden (Wegzug)", "buergerservice", 90493,
       "abmeldung abmelden wegzug ausland"),
    _s("ummeldung", "wohnen", None, "Ummelden innerhalb Duisburgs", "buergerservice", 90494,
       "ummeldung umzug adresse adressänderung wohnung"),
    _s("familienstand", "wohnen", None, "Familienstand ändern", "buergerservice", 393309,
       "heirat hochzeit scheidung verheiratet geschieden"),

    # --- Fahrzeug: Zulassung (Zulassungsstelle) ---
    _s("neuzulassung", "fahrzeug", "zulassung", "Neufahrzeug zulassen", "zulassung", 217899,
       "neuwagen auto anmelden zulassung"),
    _s("wiederzulassung", "fahrzeug", "zulassung", "Wiederzulassung (außer Betrieb gesetzt)", "zulassung", 217884,
       "wieder anmelden auto stillgelegt abgemeldet zulassung"),
    _s("import_eu_gebraucht", "fahrzeug", "zulassung", "Gebrauchtwagen-Import aus der EU", "zulassung", 217886,
       "import ausland eu gebraucht auto zulassung"),
    _s("import_eu_neu", "fahrzeug", "zulassung", "Neuwagen-Import aus der EU", "zulassung", 220237,
       "import ausland eu neu auto zulassung"),
    _s("import_nichteu_gebraucht", "fahrzeug", "zulassung", "Gebrauchtwagen-Import (Nicht-EU)", "zulassung", 217893,
       "import ausland drittstaat gebraucht auto zulassung"),
    _s("import_nichteu_neu", "fahrzeug", "zulassung", "Neuwagen-Import (Nicht-EU)", "zulassung", 217894,
       "import ausland drittstaat neu auto zulassung"),
    _s("zulassung_minderjaehrig", "fahrzeug", "zulassung", "Zulassung auf Minderjährige", "zulassung", 217885,
       "minderjährig kind jugendlich zulassung"),

    # --- Fahrzeug: Kennzeichen ---
    _s("wunschkennzeichen", "fahrzeug", "kennzeichen", "Wunschkennzeichen", "zulassung", 217908,
       "wunsch nummernschild kennzeichen"),
    _s("umkennzeichnung_wunsch", "fahrzeug", "kennzeichen", "Umkennzeichnung auf Wunschkennzeichen", "zulassung",
       217904, "wunschkennzeichen nummernschild wechseln"),
    _s("kennzeichen_beschaedigt", "fahrzeug", "kennzeichen", "Beschädigtes Kennzeichen", "zulassung", 217900,
       "kaputt nummernschild"),
    _s("plakette_beschaedigt", "fahrzeug", "kennzeichen", "Beschädigtes Siegel / HU-Plakette", "zulassung", 217901,
       "stadtsiegel tüv plakette kennzeichen"),
    _s("oldtimerkennzeichen", "fahrzeug", "kennzeichen", "Oldtimerkennzeichen", "zulassung", 217902,
       "h-kennzeichen oldtimer historisch nummernschild"),
    _s("saisonkennzeichen", "fahrzeug", "kennzeichen", "Saisonkennzeichen", "zulassung", 217903,
       "saison motorrad cabrio nummernschild"),
    _s("wechselkennzeichen", "fahrzeug", "kennzeichen", "Wechselkennzeichen (zwei Fahrzeuge)", "zulassung", 217907,
       "wechsel nummernschild zwei"),
    _s("ausfuhrkennzeichen", "fahrzeug", "kennzeichen", "Ausfuhrkennzeichen", "zulassung", 217882,
       "export ausfuhr nummernschild"),
    _s("kurzzeitkennzeichen", "fahrzeug", "kennzeichen", "Kurzzeitkennzeichen", "zulassung", 217883,
       "kurzzeit überführung probefahrt nummernschild"),

    # --- Fahrzeug: Papiere & Umschreibung ---
    _s("umschreibung_duisburg", "fahrzeug", "papiere", "Umschreibung (in Duisburg zugelassen)", "zulassung", 217857,
       "halterwechsel kauf verkauf umschreiben"),
    _s("umschreibung_extern", "fahrzeug", "papiere", "Umschreibung (nicht in Duisburg zugelassen)", "zulassung",
       217873, "halterwechsel kauf umschreiben umzug"),
    _s("zb1_adresse", "fahrzeug", "papiere", "Adressänderung Fahrzeugschein (Umzug)", "zulassung", 217935,
       "zb1 zulassungsbescheinigung adresse umzug fahrzeugschein", aliases=(217940,)),
    _s("zb1_firmensitz", "fahrzeug", "papiere", "Fahrzeugschein: Firmensitz verlegt", "zulassung", 217936,
       "zb1 firma firmensitz adresse", aliases=(217942,)),
    _s("zb_namensaenderung", "fahrzeug", "papiere", "Fahrzeugpapiere: Namensänderung", "zulassung", 217938,
       "zb1 zb2 name heirat fahrzeugbrief fahrzeugschein", aliases=(217943,)),
    _s("bs_fahrzeugschein_aenderung", "fahrzeug", "papiere", "Adresse/Name Fahrzeugschein (Bürgerservice)",
       "buergerservice", 90495, "zb1 adresse name umzug fahrzeugschein"),

    # --- Fahrzeug: Diebstahl & Verlust ---
    _s("kennzeichen_verlust", "fahrzeug", "verlust", "Kennzeichen verloren / gestohlen", "zulassung", 217921,
       "diebstahl verlust nummernschild umkennzeichnung", aliases=(217905,)),
    _s("zb2_verlust", "fahrzeug", "verlust", "Fahrzeugbrief (ZB II) verloren", "zulassung", 217922,
       "diebstahl verlust zb2 fahrzeugbrief"),
    _s("zb1_verlust", "fahrzeug", "verlust", "Fahrzeugschein (ZB I) verloren", "zulassung", 217931,
       "diebstahl verlust zb1 fahrzeugschein"),
    _s("fahrzeug_diebstahl", "fahrzeug", "verlust", "Fahrzeug gestohlen (Außerbetriebsetzung)", "zulassung",
       217920, "diebstahl auto gestohlen abmelden"),

    # --- Fahrzeug: Technik ---
    _s("katalysator", "fahrzeug", "technik", "Katalysator nachrüsten", "zulassung", 217914, "kat umwelt"),
    _s("partikelfilter", "fahrzeug", "technik", "Partikelfilter nachrüsten (Diesel)", "zulassung", 217916,
       "diesel dpf umwelt partikel"),
    _s("technische_aenderung", "fahrzeug", "technik", "Technische Änderung eintragen", "zulassung", 217918,
       "umbau eintragung tuning"),
    _s("gespann_100", "fahrzeug", "technik", "Gespann bis 100 km/h", "zulassung", 217919,
       "anhänger tempo 100 wohnwagen"),

    # --- Fahrzeug: Abmeldung ---
    _s("fahrzeug_abmeldung", "fahrzeug", "abmeldung", "Fahrzeug abmelden (Zulassungsstelle)", "zulassung", 217855,
       "abmelden außerbetriebsetzung stilllegen auto"),
    _s("bs_fahrzeug_abmeldung", "fahrzeug", "abmeldung", "Fahrzeug abmelden (Bürgerservice)", "buergerservice",
       93357, "abmelden außerbetriebsetzung stilllegen auto"),

    # --- Führerschein: Beantragen (seit Nov. 2026 nur noch im Bürgerservice, siehe MOVED) ---
    _s("bs_fs_antrag", "fuehrerschein", "antrag", "Führerschein beantragen (alle Anträge)", "buergerservice",
       90496, "erstantrag ersterteilung erster führerschein fahrerlaubnis antrag neu klasse b bf17 17 "
              "begleitet begleitetes fahren jugendlich erweiterung erweitern motorrad lkw verlängerung "
              "neuerteilung wiedererteilung entzug mpu b96 b196"),

    # --- Führerschein: Umtausch & Ersatz ---
    _s("fs_umtausch", "fuehrerschein", "umtausch", "Deutschen Führerschein umtauschen", "fahrerlaubnis", 345805,
       "umtausch pflichtumtausch karte alt grau rosa"),
    _s("bs_fs_umtausch", "fuehrerschein", "umtausch", "Führerschein umtauschen (Bürgerservice)", "buergerservice",
       93355, "umtausch pflichtumtausch karte alt grau rosa"),
    _s("fs_ersatz", "fuehrerschein", "umtausch", "Ersatz nach Verlust / Diebstahl", "fahrerlaubnis", 110007,
       "verloren gestohlen ersatzführerschein"),
    _s("fs_umschreibung_nichteu", "fuehrerschein", "umtausch", "Nicht-EU-Führerschein umschreiben",
       "fahrerlaubnis", 110023, "ausland ausländisch drittstaat umschreibung"),
    _s("fs_umschreibung_eu", "fuehrerschein", "umtausch", "EU-Führerschein umschreiben", "fahrerlaubnis", 110025,
       "ausland eu umschreibung"),
    _s("fs_dienstfuehrerschein", "fuehrerschein", "umtausch", "Dienstführerschein umschreiben", "fahrerlaubnis",
       110030, "bundeswehr polizei dienst"),

    # --- Führerschein: International ---
    _s("fs_international", "fuehrerschein", "international", "Internationaler FS (Karte aus Duisburg)",
       "fahrerlaubnis", 110022, "international ausland reise idp"),
    _s("fs_international_alt", "fuehrerschein", "international", "Internationaler FS (alter FS / andere Stadt)",
       "fahrerlaubnis", 110021, "international ausland reise idp grau rosa"),
    _s("bs_fs_international", "fuehrerschein", "international", "Internationaler FS (Bürgerservice)",
       "buergerservice", 93356, "international ausland reise idp"),

    # --- Führerschein: Beruf & Personenbeförderung ---
    _s("fs_taxischein", "fuehrerschein", "beruf", "Taxischein (Fahrgastbeförderung)", "fahrerlaubnis", 110008,
       "taxi uber mietwagen personenbeförderung p-schein"),
    _s("fs_fahrerkarte", "fuehrerschein", "beruf", "Fahrerkarte beantragen", "fahrerlaubnis", 110010,
       "fahrerkarte tachograph lkw"),
    _s("fs_schluesselzahl95", "fuehrerschein", "beruf", "Schlüsselzahl 95 eintragen", "fahrerlaubnis", 110018,
       "95 bkrfqg berufskraftfahrer module"),
    _s("fs_verlaengerung_c", "fuehrerschein", "beruf", "Verlängerung Klasse C/CE", "fahrerlaubnis", 110019,
       "lkw verlängern c ce"),
    _s("fs_verlaengerung_d", "fuehrerschein", "beruf", "Verlängerung Klasse D/DE", "fahrerlaubnis", 110020,
       "bus verlängern d de"),

    # --- Führerschein: Abholung & Versand ---
    _s("fs_abholung", "fuehrerschein", "abholung", "Führerschein abholen", "fahrerlaubnis", 108401,
       "abholung abholen fertig"),
    _s("bs_fs_abholung", "fuehrerschein", "abholung", "Führerschein abholen (Bürgerservice)", "buergerservice",
       93353, "abholung abholen aushändigen fertig"),
    _s("bs_fs_abgabe", "fuehrerschein", "abholung", "Führerschein abgeben (Bürgerservice)", "buergerservice",
       93354, "abgabe abgeben fahrverbot entgegennahme"),
    _s("fs_direktversand", "fuehrerschein", "abholung", "Adressänderung für Direktversand", "fahrerlaubnis", 131749,
       "versand post adresse"),

    # --- Führerschein: Sonstiges ---
    _s("fs_b96", "fuehrerschein", "sonstiges", "Schlüsselzahl B96 / B196 / B197", "fahrerlaubnis", 110033,
       "b96 b196 b197 anhänger motorrad automatik"),
    _s("fs_fahrschulwechsel", "fuehrerschein", "sonstiges", "Fahrschulwechsel", "fahrerlaubnis", 110027,
       "fahrschule wechseln"),
    _s("fs_theoriepruefung", "fuehrerschein", "sonstiges", "Änderung Theorieprüfung", "fahrerlaubnis", 110028,
       "theorie prüfung sprache"),
    _s("fs_wiedererteilung_vorsprache", "fuehrerschein", "sonstiges", "Vorsprache laufende Wiedererteilung",
       "fahrerlaubnis", 110031, "wiedererteilung neuerteilung vorsprache"),
    _s("fs_beratung", "fuehrerschein", "sonstiges", "Beratung zum laufenden Antrag", "fahrerlaubnis", 110032,
       "beratung antrag status"),
    _s("fs_auflagen", "fuehrerschein", "sonstiges", "Auflagen ändern (z. B. Sehhilfe)", "fahrerlaubnis", 155245,
       "brille sehhilfe auflage"),

    # --- Gewerbe ---
    _s("gewerbe_anmeldung", "gewerbe", None, "Gewerbe anmelden", "gewerbe", 349618,
       "gewerbeanmeldung selbstständig gründung firma"),
    _s("gewerbe_abmeldung", "gewerbe", None, "Gewerbe abmelden", "gewerbe", 349619, "gewerbeabmeldung aufgabe"),
    _s("gewerbe_ummeldung", "gewerbe", None, "Gewerbe ummelden", "gewerbe", 349620,
       "gewerbeummeldung änderung umzug"),
    _s("gewerbe_auskunft", "gewerbe", None, "Gewerbeauskunft / Ersatzbescheinigung", "gewerbe", 349621,
       "auskunft bescheinigung ersatz"),
    _s("gewerbezentralregister", "gewerbe", None, "Gewerbezentralregisterauszug", "gewerbe", 372904,
       "zentralregister auszug"),
    _s("reisegewerbe", "gewerbe", None, "Reisegewerbe", "gewerbe", 372905, "reisegewerbekarte markt"),
    _s("makler", "gewerbe", None, "Maklerangelegenheiten", "gewerbe", 372906, "makler immobilien 34c"),

    # --- Fundsachen (Bürgerservice) ---
    _s("fund_abgeben", "fundsachen", None, "Fundsache abgeben", "buergerservice", 93366,
       "fundbüro gefunden abgeben"),
    _s("fund_abholen", "fundsachen", None, "Fundsache abholen", "buergerservice", 93367,
       "fundbüro verloren abholen"),
    _s("fund_auskunft", "fundsachen", None, "Auskunft zu Fundsachen", "buergerservice", 93368,
       "fundbüro verloren auskunft"),

    # --- Bescheinigungen & Sonstiges (Bürgerservice) ---
    _s("fuehrungszeugnis", "sonstiges", None, "Führungszeugnis", "buergerservice", 94180,
       "polizeiliches führungszeugnis bewerbung"),
    _s("meldebescheinigung", "sonstiges", None, "Melde-/Lebens-/Aufenthaltsbescheinigung", "buergerservice", 94181,
       "bescheinigung meldebescheinigung lebensbescheinigung aufenthaltsbescheinigung"),
    _s("melderegisterauskunft", "sonstiges", None, "Melderegisterauskunft (Hausauskunft)", "buergerservice", 94182,
       "auskunft hausauskunft melderegister"),
    _s("steuer_id", "sonstiges", None, "Steuer-ID (Lohnsteuer-ID)", "buergerservice", 94183,
       "steueridentifikationsnummer steuernummer lohnsteuer finanzamt"),
    _s("beglaubigung", "sonstiges", None, "Beglaubigung (Kopie / Unterschrift)", "buergerservice", 93369,
       "beglaubigen kopie unterschrift"),
    _s("fischereischein", "sonstiges", None, "Fischereischein", "buergerservice", 93370, "angeln angelschein"),
    _s("mein_ticket", "sonstiges", None, "„Mein Ticket“", "buergerservice", 93371,
       "sozialticket ticket bus bahn"),
    _s("schwerbehindertenausweis", "sonstiges", None, "Schwerbehindertenausweis verlängern", "buergerservice",
       93372, "behinderung schwerbehindert verlängern"),
    _s("abfallsaecke", "sonstiges", None, "Abfallsäcke kaufen", "buergerservice", 93373,
       "müll müllsäcke abfall"),
    _s("zahlstelle", "sonstiges", None, "Zahlstelle", "buergerservice", 93374, "bezahlen zahlung kasse"),
    _s("untersuchungsberechtigung", "sonstiges", None, "Untersuchungsberechtigungsschein", "buergerservice", 93375,
       "jugendarbeitsschutz untersuchung arzt"),
]

SERVICES: dict[str, Service] = {s.key: s for s in _SERVICES}


# ---------------------------------------------------------------------------
# Umgezogene Dienstleistungen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MovedService:
    """Eine Dienstleistung, die eTermin noch listet, die dort aber nicht mehr
    gebucht werden kann, weil eine andere Stelle zuständig ist. Aktive Suchen
    werden beim Start auf ``new_key`` umgestellt (database/db.py), der Nutzer
    bekommt dazu einmal eine Nachricht (manager/checker.py)."""
    old_key: str
    old_name: str
    site: str
    sid: int
    new_key: str


MOVED = {m.old_key: m for m in [
    # Fahrerlaubnisbehörde, Gruppe "Fahrerlaubnisbeantragung", festgestellt 18.11.2026:
    # "Dies kann ausschließlich im Bürgerservice Ihrer Wahl erledigt werden!"
    MovedService("fs_ersterteilung", "Ersterteilung", "fahrerlaubnis", 110036, "bs_fs_antrag"),
    MovedService("fs_bf17", "Begleitetes Fahren ab 17", "fahrerlaubnis", 110037, "bs_fs_antrag"),
    MovedService("fs_erweiterung", "Erweiterung (neue Klasse)", "fahrerlaubnis", 110038, "bs_fs_antrag"),
    MovedService("fs_neuerteilung", "Neuerteilung (nach Entzug)", "fahrerlaubnis", 110039, "bs_fs_antrag"),
]}


def services_in(topic: str, subtopic: str | None = None) -> list[Service]:
    return [s for s in _SERVICES if s.topic == topic and (subtopic is None or s.subtopic == subtopic)]


def known_sids(site: str) -> set[int]:
    """Alle eTermin-IDs einer Buchungsseite, die der Katalog kennt (inkl. Aliase
    und umgezogener Dienstleistungen)."""
    return ({sid for s in _SERVICES if s.site == site for sid in (s.sid, *s.aliases)}
            | {m.sid for m in MOVED.values() if m.site == site})


def service_by_sid(site: str, sid: int) -> Service | None:
    """Katalogeintrag zu einer eTermin-ID (auch über Aliase); umgezogene → None."""
    return next((s for s in _SERVICES if s.site == site and sid in (s.sid, *s.aliases)), None)


def booking_url(service: Service) -> str:
    # Nur diese Form wählt die Dienstleistung vor und öffnet direkt den Kalender
    return f"https://www.etermin.net/{SITES[service.site].webid}/serviceid/{service.sid}"


def service_label(service: Service, location: str | None = None) -> str:
    """'Personalausweis beantragen · Bürgerservice Hamborn'"""
    place = SITES[service.site].name
    if location:
        place += f" {LOCATIONS[location]}"
    return f"{service.name} · {place}"


# ---------------------------------------------------------------------------
# Stichwortsuche
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _haystacks(service: Service) -> tuple[str, str]:
    topic = TOPICS[service.topic]
    extra = [*service.keywords, topic.label, topic.subtopics.get(service.subtopic, ""), SITES[service.site].name]
    return _normalize(service.name), _normalize(" ".join(extra))


_INDEX = [(s, *_haystacks(s)) for s in _SERVICES]


def search(query: str, limit: int = 8) -> list[Service]:
    """Findet Dienstleistungen zu einem Stichwort. Alle Wörter müssen passen;
    gibt es so keinen Treffer, reicht ein passendes Wort."""
    tokens = _normalize(query).split()
    if not tokens:
        return []

    def score(name, extra, require_all):
        hits = [3 if t in name else 1 if t in extra else 0 for t in tokens]
        if require_all and not all(hits):
            return 0
        return sum(hits)

    for require_all in (True, False):
        scored = [(score(name, extra, require_all), s) for s, name, extra in _INDEX]
        scored = [(points, s) for points, s in scored if points > 0]
        if scored:
            scored.sort(key=lambda x: (-x[0], x[1].name))
            return [s for _, s in scored[:limit]]
    return []
