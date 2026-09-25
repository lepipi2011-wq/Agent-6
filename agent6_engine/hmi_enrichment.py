"""HMI-/Anwendungs-Anreicherung — Stufe 2 nach dem Bild-Harvest.

Der Bild-Harvest findet die MASCHINE. Diese Stufe bestimmt pro Maschine, was im Bild
NICHT steht: OEM, Modell, Anwendungsart und HMI-Typ — indem sie die Quell-Seite lädt
und Claude LESEN lässt (sprach-agnostisch: versteht "comando via cavo" = Kabelsteuerung).

Diese Version:
- Verfeinerte HMI-Kategorien + mehrsprachiges Signal-Vokabular (im Prompt).
- Händler-/Marktplatz-Quellen erkannt -> OEM-Herstellerseite nachladen (löst "unklar").
- Dedup: gleiche Quell-Seite vor der Anreicherung (spart Kosten), gleiche OEM+Modell danach.
- Optionales Zurückschreiben nach Airtable.

Braucht ANTHROPIC_API_KEY; OEM-Nachladen braucht SERPAPI_KEY; Airtable optional.
"""
from __future__ import annotations
import os, re, csv, json, datetime
from urllib.parse import urlparse
from . import source_trust as _trust

HMI_KATEGORIEN = ("Kabel-Pendant", "Stationär/fest", "Funk", "Fußpedal/Vor-Ort", "unklar")

# CAN-Bus / elektrisch ansteuerbare Hydraulik — harter Scope-Filter (ohne = nicht nachrüstbar)
CAN_LEVELS = ("CAN belegt", "wahrscheinlich CAN", "wahrscheinlich rein-hydraulisch", "unklar")
CAN_VOKABULAR = {
    "direkter CAN-Beleg": "CAN, CAN-Bus, CANbus, CANopen, J1939 / CAN, CAN bus / CAN, bus CAN",
    "Steuerungssystem-Anker (CAN praktisch sicher)": "IQAN, Danfoss PVG, PLUS+1, Bosch Rexroth BODAS, "
        "Parker IQAN, Sauer-Danfoss, Epec, MdrivePlus",
    "E-Hydraulik-Anker (CAN wahrscheinlich)": "elektro-hydraulisch, elektrische Vorsteuerung, "
        "proportionale E-Steuerung / electro-hydraulic, electric pilot control, electric joystick, "
        "load-sensing electric, EHC / comando elettroidraulico / commande électrohydraulique",
    "Gegen-Anker (rein hydraulisch -> OUT)": "rein hydraulisch, manuelle Handhebel, direkte "
        "Ventilsteuerung, mechanische Vorsteuerung / manual hydraulic, direct spool valves, "
        "mechanical levers, hand levers / puramente idraulico / purement hydraulique",
}

HMI_VOKABULAR = {
    "Kabel-Pendant": "Kabel-Pendant, Hängetaster, kabelgebundenes Handbediengerät, Kabelsteuerung mit "
                     "Handgerät / cable pendant, tethered pendant, umbilical control, hand-held on cable "
                     "/ pulsantiera pensile, comando via cavo / boîtier pendant filaire",
    "Stationär/fest": "stationäres HMI, festes Kabelpult, fest verbautes Bedienpult, Steuerpult, "
                      "Bedienpult, Bedienkonsole, Fahrerstand / fixed control station, built-in control "
                      "panel, onboard console, integrated HMI / consolle fissa, quadro comandi fisso "
                      "/ poste de commande fixe, pupitre intégré",
    "Funk": "Funkfernsteuerung, Funk / radio remote, wireless remote, Scanreco, Hetronic / "
            "radiocomando / radiocommande",
    "Fußpedal/Vor-Ort": "Fußpedal, Deichsel, Vor-Ort-Bedienung / foot pedal, deadman, walk-behind, "
                        "on-board controls / pedale / pédale",
}

# Preis: Listenpreis/UVP aus Datenblatt/Shop; unter ~10k EUR lohnt der RC-Aufwand meist nicht
PREIS_HINWEISE = ("Preis, Listenpreis, UVP, ab EUR, zzgl. MwSt / price, list price, MSRP, starting at, "
                  "from USD / prezzo, prezzo di listino / prix, prix catalogue")
PREIS_SCHWELLE_EUR = 10000

# Groessen-Gate (Cluster-6 / Vorgehensweise v3): Mindestgroesse fuer einen sinnvollen
# Safety-RC-Retrofit. Niedrige Schwelle, Borderline lieber drin lassen (Pierre).
GEWICHT_MIN_T = 0.8      # Betriebsgewicht in Tonnen
LEISTUNG_MIN_KW = 8      # Motorleistung in kW


def _num(x):
    """Robuste Zahl-Extraktion (akzeptiert '1,5', '1.5 t', None)."""
    if isinstance(x, (int, float)):
        return float(x)
    if not x:
        return None
    m = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(x))
    return float(m.group().replace(",", ".")) if m else None


def groesse_status(gewicht_t, leistung_kw) -> str:
    """ok = mind. eine Dimension erreicht die Schwelle; 'zu klein' = BEIDE bekannt und beide
    darunter; 'unklar' = mind. eine Dimension fehlt und keine erreicht die Schwelle.
    Grund: Bei OR-Logik kann eine unbekannte Dimension die Maschine noch qualifizieren ->
    dann NICHT disqualifizieren (False Positives akzeptabel)."""
    g, l = _num(gewicht_t), _num(leistung_kw)
    if (g is not None and g >= GEWICHT_MIN_T) or (l is not None and l >= LEISTUNG_MIN_KW):
        return "ok"
    if g is not None and l is not None:      # beide bekannt, keine Schwelle erreicht
        return "zu klein"
    return "unklar"


# --- Bild-Heuristik Betriebsschnittstelle (Pierre-Regel, 2026-09-24) -------------------
# WICHTIG: CAN/Gewicht/Leistung lassen sich NICHT aus dem Bild extrahieren -> dafuer ist das
# Datenblatt / --verify-specs zustaendig (Text). Das BILD liefert ein anderes, starkes Signal:
# die Betriebsschnittstelle am Fahrzeug. Fehlen Kabine, Plattform, Sitz UND Deichsel, dann wird
# die Maschine nicht von einem Bediener am/auf dem Geraet gefuehrt -> sie ist AUTONOM oder bereits
# FERNGESTEUERT. Beides ist NICHT das Ziel (autonom = RC-Fit fraglich; RC vorhanden = Verdraengung).
# Ist mindestens eine Betriebsschnittstelle sichtbar, ist der Bediener am Geraet -> Kandidat fuer
# eine RC-Nachruestung -> In-Scope-Signal. (Belegt durch Review: 'pedana operatore stand-on' = 68% Ziel.)
def operator_interface_scope(kabine=False, plattform=False, sitz=False, deichsel=False) -> str:
    """'bediener-praesent' (In-Scope-Signal) wenn Kabine/Plattform/Sitz/Deichsel sichtbar,
    sonst 'autonom-oder-RC' (Out-of-Scope-Signal: autonom oder bereits ferngesteuert)."""
    if any((kabine, plattform, sitz, deichsel)):
        return "bediener-praesent"
    return "autonom-oder-RC"


def priorisiere(can_bus, preis_eur, hmi_typ, ist_ziel=True, claude_urteil="", groesse="unklar") -> str:
    if not ist_ziel or claude_urteil == "Out-of-Scope" or groesse == "zu klein":
        return "X"                       # ausser Scope -> nicht an den Vertrieb
    """A = CAN + Preis ueber Schwelle (bester Fit), B = CAN oder Preis ok, C = hydraulisch/guenstig.
    Hydraulische bleiben drin (Pierres Vorgabe), CAN hat aber Vorrang."""
    can_ok = can_bus in ("CAN belegt", "wahrscheinlich CAN")
    preis_ok = (preis_eur is None) or (preis_eur >= PREIS_SCHWELLE_EUR)
    if can_ok and preis_ok:
        return "A"
    if can_ok or preis_ok:
        return "B"
    return "C"


_DEALER = ("masterwholesale.", "houseofcontractors.", "mascus.", "machineryzone.",
           "directindustry.", "europages.", "exapro.", "ebay.", "amazon.", "alibaba.",
           "indiamart.", "made-in-china.", "trademachines.", "ritchiespecs.", "equipmenttrader.")


def _domain(u):
    try:
        d = urlparse(u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_dealer(url) -> bool:
    d = _domain(url)
    return any(x in d for x in _DEALER)


# Marktplatz-/Listing-Aggregatoren: das Bild liegt auf deren CDN, die Listing-Seite blockt
# Bots oder ist reines JS -> liefert leeren Text. Das ist NIE die OEM-Seite. Gegenmassnahme:
# tote Seite gar nicht erst fetchen, sondern per Bildtitel/Modell die echte Herstellerseite suchen.
_AGGREGATOR = ("machinerytrader.", "sandhills.", "marketbook.", "mascus.", "machineryzone.",
               "ritchiespecs.", "equipmenttrader.", "trademachines.", "ironplanet.",
               "govplanet.", "rockanddirt.", "truckpaper.", "forestrytrader.",
               "mylittlesalesman.", "cranenetwork.", "plantandequipment.", "autoline",
               "agriaffaires.", "truck1.")


def is_aggregator(url) -> bool:
    d = _domain(url)
    return any(x in d for x in _AGGREGATOR)


def _pdf_to_text(data: bytes, max_chars=6000) -> str:
    try:
        import io, logging
        logging.getLogger("pypdf").setLevel(logging.ERROR)   # "Impossible to decode"-Warnungen stumm
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        out = []
        for page in reader.pages[:15]:
            out.append(page.extract_text() or "")
            if sum(len(x) for x in out) > max_chars:
                break
        return re.sub(r"\s+", " ", " ".join(out)).strip()[:max_chars]
    except Exception:
        return ""


def fetch_page_text(url, timeout=20, max_chars=6000) -> str:
    """Lädt HTML ODER PDF und gibt Text zurück (PDF via pypdf)."""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
            "Accept-Language": "de,en;q=0.9"})
        r.raise_for_status()
        ct = r.headers.get("content-type", "").lower()
        if "pdf" in ct or url.lower().split("?")[0].endswith(".pdf"):
            return _pdf_to_text(r.content, max_chars)
        if "html" not in ct and "text" not in ct:
            return ""
        html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception:
        return ""


def _find_datasheet_pdf(url, timeout=20):
    """Sucht auf der HTML-Seite einen Link zu einem Datenblatt-PDF (dort steht CAN meist)."""
    try:
        import requests
        from urllib.parse import urljoin
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
            "Accept-Language": "de,en;q=0.9"})
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "").lower():
            return None
        links = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', r.text, re.I)
        # Datenblatt/technische PDFs bevorzugen
        pref = [l for l in links if re.search(r"(datasheet|datenblatt|technical|technische|spec|prospekt|brochure)", l, re.I)]
        target = (pref or links)
        return urljoin(url, target[0]) if target else None
    except Exception:
        return None


def fetch_deep(url) -> str:
    """HTML-Text + (falls vorhanden) Text des verlinkten Datenblatt-PDFs.
    Robust: das PDF ist NUR ein Bonus und kann den HTML-Text nie ersetzen/loeschen.
    Liefert die tiefe URL nichts (404/leer), wird die Domain-Startseite versucht."""
    text = ""
    try:
        text = fetch_page_text(url) or ""
    except Exception:
        text = ""
    # Fallback: tiefe Produkt-URL tot -> Startseite der Domain lesen
    if len(text) < 200:
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            if p.scheme and p.netloc:
                root = f"{p.scheme}://{p.netloc}"
                if root.rstrip("/") != url.rstrip("/"):
                    alt = fetch_page_text(root) or ""
                    if len(alt) > len(text):
                        text = alt
        except Exception:
            pass
    # Datenblatt-PDF nur ZUSAETZLICH anhaengen (nie ersetzen)
    try:
        pdf = _find_datasheet_pdf(url)
        if pdf:
            ptext = fetch_page_text(pdf) or ""
            if ptext:
                text = (text + " \n[DATENBLATT-PDF]\n " + ptext)[:9000]
    except Exception:
        pass
    return text


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def _parse_json(txt):
    s = (txt or "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            return {}
    return {}


# Few-Shot aus echten Review-Verdikten (kalibriert die Urteilsschicht gegen die Mensch-Labels;
# adressiert die gemessene Ueber-Ablehnung: Baseline-Recall 16 %). Kurz halten (Kosten).
FEW_SHOT_URTEIL = (
    "\nBEISPIELE (so urteilen wir):\n"
    "1) Kettengetriebener Stand-on-/Aufsitz-Mulcher, hydrostatisch, KEIN CAN erwaehnt -> "
    "'In-Scope' (Anwendung passt; fehlendes CAN ist kein Ausschluss -> Aktuator-Retrofit).\n"
    "2) Kettenmaschine, die laut Text BEREITS per Funk/Radio ferngesteuert wird -> 'Out-of-Scope' "
    "(Verdraengung, schon RC).\n"
    "3) Autonomer/roboterhafter Kettenschlepper ohne Kabine/Plattform/Sitz/Deichsel -> 'Out-of-Scope' "
    "(autonom, kein Bediener am Geraet).\n"
    "4) Rad-/Reifen-Maschine oder blosses Anbaugeraet/Bauteil -> 'Out-of-Scope'.\n"
    "5) Text leer/sehr duenn oder Aggregator-/Social-/Listing-Seite (kein OEM-Inhalt) -> 'Unsicher' "
    "(NICHT Out-of-Scope; Kandidat wird spaeter nachaufgeloest statt verworfen).\n"
)


def enrich(page_text, image_url, pattern, cfg, client=None, lessons="") -> dict:
    client = client or _client()
    if client is None:
        return {"oem": "", "modell": "", "anwendung": "", "hmi_typ": "unklar",
                "can_bus": "unklar", "can_reason": "", "preis_eur": None, "preis_beleg": "",
                "gewicht_t": None, "leistung_kw": None, "groesse_beleg": "",
                "sprache": "", "reason": "kein-key"}
    model = cfg.get("harvest", {}).get("vlm_model", "claude-haiku-4-5-20251001")
    vokab = "\n".join(f"  - {k}: {v}" for k, v in HMI_VOKABULAR.items())
    can_vokab = "\n".join(f"  - {k}: {v}" for k, v in CAN_VOKABULAR.items())
    prompt = (
        "Du bekommst den Text einer Produktseite/eines Datenblatts (BELIEBIGE Sprache). "
        "Pruefe ZUERST, ob es ueberhaupt um eine KETTENGETRIEBENE (Raupen-)Maschine geht "
        "(Bagger, Lader, Dumper, Roboter etc. auf Ketten/Raupen). Ermittle:\n"
        "- ist_zielmaschine: true nur wenn es eine kettengetriebene Maschine ist; false bei "
        "allem anderen (z.B. Dosieranlage, Rad-Maschine, Bauteil, Nachrichtenartikel, leere Seite)\n"
        "- oem: Herstellerfirma\n- modell: Modell-/Seriename\n"
        "- anwendung: Anwendungsart auf DEUTSCH (z.B. Abbruchroboter, Mini-Dumper, Stubbenfräse)\n"
        "- hmi_typ: EINE dieser Kategorien anhand des Vokabulars:\n" + vokab +
        "\n  - unklar: wenn der Text keine Steuerungs-Info enthält (NICHT raten)\n"
        "- can_bus: Suche AKTIV nach CAN-Bus / elektrisch ansteuerbarer Hydraulik anhand:\n" + can_vokab +
        "\n  Werte: 'CAN belegt' (CAN/CANopen/J1939 direkt genannt), 'wahrscheinlich CAN' "
        "(IQAN/Danfoss/BODAS oder E-Hydraulik genannt), 'wahrscheinlich rein-hydraulisch' "
        "(Gegen-Anker genannt), 'unklar' (nichts dazu im Text). "
        "WICHTIG: Fehlendes CAN ist KEIN Ausschlussgrund. Passt die Anwendung, fehlt nur CAN, "
        "ist eine Aktuator-Nachrüstung denkbar -> Kandidat BLEIBT (Regel Pierre 'no can').\n"
        "- can_reason: Textbeleg für can_bus (welche Stelle)\n"
        "- preis_eur: Listenpreis/UVP als ZAHL in EUR (USD/GBP grob umrechnen), sonst null. "
        f"Achte auf: {PREIS_HINWEISE}\n"
        "- preis_beleg: Textstelle zum Preis (Originalangabe mit Währung)\n"
        "- gewicht_t: Betriebsgewicht als ZAHL in Tonnen (kg/lbs umrechnen: 1500 kg = 1.5), sonst null. "
        "Suche: Operating Weight, Betriebsgewicht, Gross Weight, Gewicht, peso, poids\n"
        "- leistung_kw: Motorleistung als ZAHL in kW (HP/PS umrechnen: 1 HP = 0.75 kW), sonst null. "
        "Suche: Motorleistung, engine power, kW, HP, PS, potenza, puissance\n"
        "- groesse_beleg: Textstelle zu Gewicht/Leistung (Originalangabe mit Einheit)\n"
        "- sprache: Sprache der Seite\n- reason: kurze Begründung mit Textbeleg für hmi_typ\n"
        "- claude_urteil: DEIN eigenes Scope-Urteil, unabhaengig vom Pattern-Vorschlag: "
        "'In-Scope' (kettengetrieben, im Zielsegment; fehlendes CAN allein ist KEIN Grund fuer Out), "
        "'Out-of-Scope' (Raeder/Bauteil/keine Zielmaschine ODER schon ferngesteuert=Verdraengung "
        "ODER autonom), 'Unsicher' (Quelle zu duenn).\n"
        "  BILD-/BAUART-HEURISTIK (stark): Fehlen Kabine, Plattform, Sitz UND Deichsel, wird die "
        "Maschine nicht vom Bediener am Geraet gefuehrt -> sie ist AUTONOM oder bereits FERNGESTEUERT "
        "-> Out-of-Scope. Ist eine dieser Betriebsschnittstellen vorhanden (Bediener am Geraet) -> "
        "starkes In-Scope-Signal (RC-Nachruestung moeglich).\n"
        "- claude_konfidenz: wie sicher du bist (0.0-1.0)\n"
        "- claude_begruendung: 1 Satz, warum dieses Urteil\n"
        "WICHTIG: Urteile NICHT vorschnell 'Out-of-Scope'. Nur bei klarem Gegenbeleg (Raeder/Bauteil/"
        "autonom/schon-RC). Ist die Quelle zu duenn, waehle 'Unsicher'.\n"
        + FEW_SHOT_URTEIL
        + (lessons or "") +
        f"\n\nSeitentext:\n{page_text[:8000]}\n\n"
        'Antworte NUR JSON {"ist_zielmaschine","oem","modell","anwendung","hmi_typ","can_bus",'
        '"can_reason","preis_eur","preis_beleg","gewicht_t","leistung_kw","groesse_beleg",'
        '"sprache","reason"}.')
    try:
        msg = client.messages.create(model=model, max_tokens=700,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        d = _parse_json(txt)
        d.setdefault("ist_zielmaschine", True)
        d.setdefault("claude_urteil", "Unsicher")
        d.setdefault("claude_konfidenz", 0.0)
        d.setdefault("claude_begruendung", "")
        d.setdefault("hmi_typ", "unklar")
        d.setdefault("can_bus", "unklar")
        d.setdefault("preis_eur", None)
        d.setdefault("gewicht_t", None)
        d.setdefault("leistung_kw", None)
        for k in ("oem", "modell", "anwendung", "sprache", "reason", "can_reason", "preis_beleg",
                  "groesse_beleg"):
            d.setdefault(k, "")
        return d
    except Exception as e:
        return {"ist_zielmaschine": True, "oem": "", "modell": "", "anwendung": "",
                "hmi_typ": "unklar", "can_bus": "unklar", "can_reason": "", "preis_eur": None,
                "preis_beleg": "", "gewicht_t": None, "leistung_kw": None, "groesse_beleg": "",
                "sprache": "", "reason": f"fehler:{type(e).__name__}",
                "claude_urteil": "Unsicher", "claude_konfidenz": 0.0, "claude_begruendung": ""}


def default_resolver(cfg):
    from .text_harvester import SerpTextSearcher, source_score
    from .image_search_harvester import is_junk as _is_junk
    searcher = SerpTextSearcher(cfg)

    def _resolve(oem, modell, seed=""):
        # Suchbegriff: bevorzugt OEM+Modell, sonst der Bildtitel/die Query
        begriff = (f"{oem} {modell}".strip() or seed).strip()
        if not begriff:
            return None
        for q in (f"{begriff} official manufacturer specifications",
                  f"{begriff} Hersteller Datenblatt"):
            for res in searcher.search(q, n=6):
                u = res.get("url", "")
                if u and not is_dealer(u) and not _is_junk(u) and source_score(u) >= 3:
                    return u
        return None
    return _resolve


def _call_resolver(fn, oem, modell, seed):
    """Ruft den Resolver seed-tolerant (aeltere Resolver kennen kein seed)."""
    try:
        return fn(oem, modell, seed=seed)
    except TypeError:
        return fn(oem, modell)


def run(cfg, manifest_path="agent6_image_candidates.json",
        out_csv="agent6_enriched.csv", limit=None,
        fetcher=None, enricher=None, resolver=None, airtable=None, resolve_oem=True,
        lessons="") -> dict:
    fetcher = fetcher or fetch_deep
    client = _client()
    enrich_fn = enricher or (lambda text, url, pat: enrich(text, url, pat, cfg, client, lessons))
    resolve_fn = resolver if resolver is not None else (default_resolver(cfg) if resolve_oem else None)
    if isinstance(manifest_path, list):
        cands = manifest_path                      # direkt uebergebene Kandidaten
    else:
        try:
            cands = json.load(open(manifest_path, encoding="utf-8"))
        except Exception:
            return {"error": f"Manifest nicht lesbar: {manifest_path}"}

    seen_pages, uniq = set(), []
    for c in cands:
        page = c.get("page") or c.get("url")
        if page in seen_pages:
            continue
        seen_pages.add(page)
        uniq.append(c)

    rows, stats = [], {"input": len(cands), "nach_seiten_dedup": len(uniq), "enriched": 0,
                       "oem_nachgeladen": 0, "via_aggregator": 0, "pendant": 0, "stationaer": 0,
                       "funk": 0, "fusspedal": 0, "unklar": 0, "final": 0, "rows_geschrieben": 0,
                       "airtable_updated": 0}
    # Anreicherung EINMAL je Quell-Seite (spart Kosten)
    page_enr = {}
    from .image_search_harvester import is_junk
    for c in uniq:
        if limit and stats["enriched"] >= limit:
            break
        page = c.get("page") or c.get("url")
        seed = (c.get("title") or c.get("query") or "").strip()
        # "worthless" = Social/Stock/Thumbnail-CDN/keine Domain -> keine lesbare Produktseite.
        # "agg" = Marktplatz/Handels-Aggregator/Haendler -> NICHT die OEM-Seite, aber aufloesbar.
        worthless = (not page) or _trust.block_reason(page) in (
            "social/stock", "cdn/thumbnail", "keine-domain")
        agg = is_aggregator(page) or _trust.is_marketplace(page) or is_dealer(page)
        # Wertlose ODER Aggregator-Quelle: der Seite nicht trauen -> per Bildtitel/Modell die
        # echte Herstellerseite suchen und DIESE anreichern. Ersetzt komplett, auch bei hmi "unklar".
        if (worthless or agg) and resolve_fn and seed:
            oem_url = _call_resolver(resolve_fn, "", "", seed)
            if oem_url:
                d = enrich_fn(fetcher(oem_url), c.get("url", ""), c.get("pattern", ""))
                if not d.get("ist_zielmaschine", True):
                    d["anwendung"] = "AUSSER SCOPE: " + (d.get("anwendung") or "keine Raupenmaschine")
                page_enr[page] = (d, oem_url)
                stats["enriched"] += 1
                stats["oem_nachgeladen"] += 1
                if agg:
                    stats["via_aggregator"] += 1
                continue
        if worthless:
            page_enr[page] = ({"ist_zielmaschine": False, "oem": "", "modell": "",
                               "anwendung": "AUSSER SCOPE: unbrauchbare Quelle",
                               "hmi_typ": "unklar", "can_bus": "unklar", "can_reason": "",
                               "preis_eur": None, "preis_beleg": "", "sprache": "", "reason": "Junk-Quelle",
                               "claude_urteil": "Out-of-Scope", "claude_konfidenz": 0.9,
                               "claude_begruendung": "Quelle ohne Produktseite, keine OEM-Seite auffindbar"}, page)
            stats["enriched"] += 1
            continue
        d = enrich_fn(fetcher(page) if page else "", c.get("url", ""), c.get("pattern", ""))
        stats["enriched"] += 1
        if not d.get("ist_zielmaschine", True):
            d["anwendung"] = "AUSSER SCOPE: " + (d.get("anwendung") or "keine Raupenmaschine")
        used_page = page
        # OEM-Seite nachladen bei unklar (Haendler ODER generell), Titel als Zusatz-Seed
        if d.get("hmi_typ") == "unklar" and resolve_fn:
            oem_url = _call_resolver(resolve_fn, d.get("oem", ""), d.get("modell", ""), seed)
            if oem_url and oem_url != page:
                d2 = enrich_fn(fetcher(oem_url), c.get("url", ""), c.get("pattern", ""))
                if d2.get("hmi_typ") != "unklar":
                    d, used_page = d2, oem_url
                    stats["oem_nachgeladen"] += 1
        page_enr[page] = (d, used_page)

    # Ergebnis auf ALLE Original-Kandidaten derselben Seite verteilen -> jeder Airtable-Record wird befüllt
    for c in cands:
        page = c.get("page") or c.get("url")
        if page not in page_enr:
            continue
        d, used_page = page_enr[page]
        gstat = groesse_status(d.get("gewicht_t"), d.get("leistung_kw"))
        rows.append({"pattern": c.get("pattern", ""), "oem": d.get("oem") or "",
                     "modell": d.get("modell") or "", "anwendung": d.get("anwendung") or "",
                     "hmi_typ": d.get("hmi_typ", "unklar"), "can_bus": d.get("can_bus", "unklar"),
                     "can_reason": d.get("can_reason", ""),
                     "preis_eur": d.get("preis_eur"), "preis_beleg": d.get("preis_beleg", ""),
                     "gewicht_t": d.get("gewicht_t"), "leistung_kw": d.get("leistung_kw"),
                     "groesse_status": gstat, "groesse_beleg": d.get("groesse_beleg", ""),
                     "claude_urteil": d.get("claude_urteil", "Unsicher"),
                     "claude_konfidenz": d.get("claude_konfidenz", 0.0),
                     "claude_begruendung": d.get("claude_begruendung", ""),
                     "prioritaet": priorisiere(d.get("can_bus", "unklar"), d.get("preis_eur"),
                                               d.get("hmi_typ", "unklar"),
                                               d.get("ist_zielmaschine", True),
                                               d.get("claude_urteil", ""), gstat),
                     "sprache": d.get("sprache", ""),
                     "reason": d.get("reason", ""), "bild_url": c.get("url", ""),
                     "quell_seite": used_page, "harvested_at": datetime.date.today().isoformat()})
    stats["ausser_scope"] = sum(1 for r in rows if r.get("prioritaet") == "X")
    stats["rows_geschrieben"] = len(rows)
    for s in ("ok", "zu klein", "unklar"):
        stats["groesse_" + s.replace(" ", "_")] = sum(1 for r in rows if r.get("groesse_status") == s)

    best = {}
    for r in rows:
        key = (str(r.get("oem") or "").strip().lower(), str(r.get("modell") or "").strip().lower())
        if key == ("", ""):
            best[id(r)] = r
            continue
        if key not in best or (best[key]["hmi_typ"] == "unklar" and r["hmi_typ"] != "unklar"):
            best[key] = r
    final = list(best.values())
    for r in final:
        stats[_bucket(r["hmi_typ"])] += 1
    for r in final:
        cb = r.get("can_bus") or "unklar"
        stats["can_belegt" if cb == "CAN belegt" else
              "can_wahrsch" if cb == "wahrscheinlich CAN" else
              "can_hydraulik" if "hydraulisch" in cb else "can_unklar"] = \
            stats.get("can_belegt" if cb == "CAN belegt" else
                      "can_wahrsch" if cb == "wahrscheinlich CAN" else
                      "can_hydraulik" if "hydraulisch" in cb else "can_unklar", 0) + 1
    for r in final:
        k = "prio_" + r.get("prioritaet", "C")
        stats[k] = stats.get(k, 0) + 1
    stats["final"] = len(final)

    _write_csv(final, out_csv)
    json.dump(final, open(out_csv.replace(".csv", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if airtable and getattr(airtable, "enabled", False):
        stats["airtable_updated"] = airtable.update_enrichment(rows)   # ALLE Records befüllen
        stats["airtable_failed"] = getattr(airtable, "write_failures", 0)
        # Groessen-Felder SEPARAT (eigene Spalten): ein fehlender Spaltenname reisst so NICHT
        # den Kern-Write (OEM/HMI/CAN) mit. Zahlen als String -> robust fuer Text- ODER Zahl-Spalte.
        size_rows = [{"bild_url": r.get("bild_url"),
                      "gewicht_t": ("" if r.get("gewicht_t") in (None, "") else str(r.get("gewicht_t"))),
                      "leistung_kw": ("" if r.get("leistung_kw") in (None, "") else str(r.get("leistung_kw"))),
                      "groesse_status": r.get("groesse_status", "")} for r in rows]
        airtable.update_fields(size_rows, {"Gewicht-t": "gewicht_t", "Leistung-kW": "leistung_kw",
                                           "Größe-Status": "groesse_status"})
        stats["airtable_size_failed"] = getattr(airtable, "write_failures", 0)
    stats["out_csv"] = out_csv
    return stats


def _bucket(hmi):
    h = hmi or ""
    if "Pendant" in h or "Kabel" in h:
        return "pendant"
    if "Stationär" in h or "fest" in h or "Fix" in h or "fix" in h:
        return "stationaer"
    if "Funk" in h:
        return "funk"
    if "Fußpedal" in h or "Vor-Ort" in h:
        return "fusspedal"
    return "unklar"


def _write_csv(rows, path):
    cols = ["prioritaet", "claude_urteil", "claude_konfidenz", "claude_begruendung",
            "pattern", "oem", "modell", "anwendung", "hmi_typ", "can_bus",
            "can_reason", "preis_eur", "preis_beleg", "gewicht_t", "leistung_kw",
            "groesse_status", "groesse_beleg", "sprache", "reason", "bild_url",
            "quell_seite", "harvested_at"]
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except Exception:
        pass


def main():
    import argparse
    from .config import load_config
    ap = argparse.ArgumentParser(description="HMI-/Anwendungs-Anreicherung (Stufe 2)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--manifest", default="agent6_image_candidates.json")
    ap.add_argument("--from-airtable", dest="from_airtable", action="store_true",
                    help="Kandidaten aus Airtable holen (alle Records ohne HMI-Typ) statt aus dem Manifest")
    ap.add_argument("--reenrich-unsicher", dest="reenrich_unsicher", action="store_true",
                    help="Statt leerer HMI-Typ: Records mit Claude-Urteil 'Unsicher' erneut "
                         "anreichern (holt bereits geladene, unaufgeloeste OEM-Quellen nach)")
    ap.add_argument("--reenrich-all", dest="reenrich_all", action="store_true",
                    help="ALLE Records komplett neu anreichern (voller Re-Run ueber den Bestand)")
    ap.add_argument("--out", default="agent6_enriched.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-resolve", dest="no_resolve", action="store_true",
                    help="OEM-Seite bei Händlerquellen NICHT nachladen")
    ap.add_argument("--airtable", action="store_true", help="Ergebnisse zurück in Airtable schreiben")
    ap.add_argument("--lessons", default=None,
                    help="CSV/JSON mit bestaetigten Verdikten -> Lehrbeispiele in den Prompt (Weg 1)")
    args = ap.parse_args()
    lessons = ""
    if args.lessons:
        import os as _os
        if not _os.path.exists(args.lessons):
            print(f"  ⚠ Lessons-Datei nicht gefunden: {args.lessons} — Lauf geht OHNE Lehrbeispiele weiter.")
        else:
            try:
                from .scope_score import load_verdikt_rows, build_lessons
                lessons = build_lessons(load_verdikt_rows(args.lessons))
                print(f"  Lehrbeispiele geladen: {lessons.count(chr(10)+'  - ')} Verdikte im Prompt")
            except Exception as e:
                print(f"  ⚠ Lessons konnten nicht geladen werden ({e}) — Lauf geht OHNE weiter.")
    cfg = load_config(args.config)
    at = None
    if args.airtable or args.from_airtable:
        from .image_search_harvester import AirtableWriter
        at = AirtableWriter(cfg=cfg)
    source = args.manifest
    if args.from_airtable:
        if not (at and at.enabled):
            print("AIRTABLE_TOKEN fehlt — kann Kandidaten nicht laden."); return
        if args.reenrich_all:
            source = at.candidates_all(limit=args.limit)
            print(f"  Re-Enrichment (ALLE): {len(source)} Records geladen")
        elif args.reenrich_unsicher:
            source = at.candidates_reenrich("Unsicher", limit=args.limit)
            print(f"  Re-Enrichment: {len(source)} 'Unsicher'-Records geladen")
        else:
            source = at.candidates_missing("HMI-Typ", limit=args.limit)
            print(f"  Aus Airtable geladen: {len(source)} Records ohne HMI-Typ")
        if getattr(at, "read_failed", False):
            import sys
            print("  ⚠ ABBRUCH: Airtable-Lesefehler — Kandidatenliste unvollstaendig. "
                  "Netz/DNS pruefen und erneut starten.")
            sys.exit(3)
    res = run(cfg, manifest_path=source, out_csv=args.out,
              limit=None if args.from_airtable else args.limit,
              airtable=(at if args.airtable else None), resolve_oem=not args.no_resolve,
              lessons=lessons)
    print("HMI-ANREICHERUNG:", res)
    if res.get("airtable_failed"):
        import sys
        print(f"  ⚠ EXIT 2: {res['airtable_failed']} Records NICHT in Airtable geschrieben "
              f"(Daten liegen in {res.get('out_csv')}). Nach Netz-Fix erneut mit --airtable laufen.")
        sys.exit(2)


if __name__ == "__main__":
    main()
