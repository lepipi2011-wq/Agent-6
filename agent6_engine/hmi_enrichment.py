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


def priorisiere(can_bus, preis_eur, hmi_typ, ist_ziel=True) -> str:
    if not ist_ziel:
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


def enrich(page_text, image_url, pattern, cfg, client=None, lessons="") -> dict:
    client = client or _client()
    if client is None:
        return {"oem": "", "modell": "", "anwendung": "", "hmi_typ": "unklar",
                "can_bus": "unklar", "can_reason": "", "preis_eur": None, "preis_beleg": "", "sprache": "", "reason": "kein-key"}
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
        "(Gegen-Anker genannt), 'unklar' (nichts dazu im Text). Ohne CAN/E-Hydraulik ist die "
        "Maschine NICHT nachrüstbar.\n"
        "- can_reason: Textbeleg für can_bus (welche Stelle)\n"
        "- preis_eur: Listenpreis/UVP als ZAHL in EUR (USD/GBP grob umrechnen), sonst null. "
        f"Achte auf: {PREIS_HINWEISE}\n"
        "- preis_beleg: Textstelle zum Preis (Originalangabe mit Währung)\n"
        "- sprache: Sprache der Seite\n- reason: kurze Begründung mit Textbeleg für hmi_typ\n"
        "- claude_urteil: DEIN eigenes Scope-Urteil, unabhaengig vom Pattern-Vorschlag: "
        "'In-Scope' (kettengetrieben, RC-nachruestbar, im Zielsegment), 'Out-of-Scope' "
        "(Raeder/Bauteil/keine Zielmaschine), 'Unsicher' (Quelle zu duenn)\n"
        "- claude_konfidenz: wie sicher du bist (0.0-1.0)\n"
        "- claude_begruendung: 1 Satz, warum dieses Urteil\n"
        + (lessons or "") +
        f"\n\nSeitentext:\n{page_text[:8000]}\n\n"
        'Antworte NUR JSON {"ist_zielmaschine","oem","modell","anwendung","hmi_typ","can_bus",'
        '"can_reason","preis_eur","preis_beleg","sprache","reason"}.')
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
        for k in ("oem", "modell", "anwendung", "sprache", "reason", "can_reason", "preis_beleg"):
            d.setdefault(k, "")
        return d
    except Exception as e:
        return {"ist_zielmaschine": True, "oem": "", "modell": "", "anwendung": "",
                "hmi_typ": "unklar", "can_bus": "unklar", "can_reason": "", "preis_eur": None,
                "preis_beleg": "", "sprache": "", "reason": f"fehler:{type(e).__name__}",
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
                       "oem_nachgeladen": 0, "pendant": 0, "stationaer": 0, "funk": 0,
                       "fusspedal": 0, "unklar": 0, "final": 0, "rows_geschrieben": 0,
                       "airtable_updated": 0}
    # Anreicherung EINMAL je Quell-Seite (spart Kosten)
    page_enr = {}
    from .image_search_harvester import is_junk
    for c in uniq:
        if limit and stats["enriched"] >= limit:
            break
        page = c.get("page") or c.get("url")
        seed = (c.get("title") or c.get("query") or "").strip()
        junk = (not page) or is_junk(page)
        # Junk-Quelle: NICHT sofort aufgeben, sondern per Bildtitel die OEM-Seite suchen
        if junk and resolve_fn and seed:
            oem_url = _call_resolver(resolve_fn, "", "", seed)
            if oem_url:
                d = enrich_fn(fetcher(oem_url), c.get("url", ""), c.get("pattern", ""))
                if not d.get("ist_zielmaschine", True):
                    d["anwendung"] = "AUSSER SCOPE: " + (d.get("anwendung") or "keine Raupenmaschine")
                page_enr[page] = (d, oem_url)
                stats["enriched"] += 1
                stats["oem_nachgeladen"] += 1
                continue
        if junk:
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
        rows.append({"pattern": c.get("pattern", ""), "oem": d.get("oem") or "",
                     "modell": d.get("modell") or "", "anwendung": d.get("anwendung") or "",
                     "hmi_typ": d.get("hmi_typ", "unklar"), "can_bus": d.get("can_bus", "unklar"),
                     "can_reason": d.get("can_reason", ""),
                     "preis_eur": d.get("preis_eur"), "preis_beleg": d.get("preis_beleg", ""),
                     "claude_urteil": d.get("claude_urteil", "Unsicher"),
                     "claude_konfidenz": d.get("claude_konfidenz", 0.0),
                     "claude_begruendung": d.get("claude_begruendung", ""),
                     "prioritaet": priorisiere(d.get("can_bus", "unklar"), d.get("preis_eur"),
                                               d.get("hmi_typ", "unklar"),
                                               d.get("ist_zielmaschine", True)),
                     "sprache": d.get("sprache", ""),
                     "reason": d.get("reason", ""), "bild_url": c.get("url", ""),
                     "quell_seite": used_page, "harvested_at": datetime.date.today().isoformat()})
    stats["ausser_scope"] = sum(1 for r in rows if r.get("prioritaet") == "X")
    stats["rows_geschrieben"] = len(rows)

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
            "can_reason", "preis_eur", "preis_beleg", "sprache", "reason", "bild_url",
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
        source = at.candidates_missing("HMI-Typ", limit=args.limit)
        print(f"  Aus Airtable geladen: {len(source)} Records ohne HMI-Typ")
    res = run(cfg, manifest_path=source, out_csv=args.out,
              limit=None if args.from_airtable else args.limit,
              airtable=(at if args.airtable else None), resolve_oem=not args.no_resolve,
              lessons=lessons)
    print("HMI-ANREICHERUNG:", res)


if __name__ == "__main__":
    main()
