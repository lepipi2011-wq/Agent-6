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


def fetch_page_text(url, timeout=20, max_chars=5000) -> str:
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "html" not in ct and "text" not in ct:
            return ""
        html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", r.text)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception:
        return ""


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


def enrich(page_text, image_url, pattern, cfg, client=None) -> dict:
    client = client or _client()
    if client is None:
        return {"oem": "", "modell": "", "anwendung": "", "hmi_typ": "unklar",
                "sprache": "", "reason": "kein-key"}
    model = cfg.get("harvest", {}).get("vlm_model", "claude-haiku-4-5-20251001")
    vokab = "\n".join(f"  - {k}: {v}" for k, v in HMI_VOKABULAR.items())
    prompt = (
        "Du bekommst den Text einer Produktseite (BELIEBIGE Sprache) zu einer "
        "kettengetriebenen (Raupen-)Maschine. Ermittle:\n"
        "- oem: Herstellerfirma\n- modell: Modell-/Seriename\n"
        "- anwendung: Anwendungsart auf DEUTSCH (z.B. Abbruchroboter, Mini-Dumper, Stubbenfräse)\n"
        "- hmi_typ: EINE dieser Kategorien anhand des Vokabulars:\n" + vokab +
        "\n  - unklar: wenn der Text keine Steuerungs-Info enthält (NICHT raten)\n"
        "- sprache: Sprache der Seite\n- reason: kurze Begründung mit Textbeleg für hmi_typ\n"
        f"\nSeitentext:\n{page_text[:4000]}\n\n"
        'Antworte NUR JSON {"oem","modell","anwendung","hmi_typ","sprache","reason"}.')
    try:
        msg = client.messages.create(model=model, max_tokens=300,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        d = _parse_json(txt)
        d.setdefault("hmi_typ", "unklar")
        for k in ("oem", "modell", "anwendung", "sprache", "reason"):
            d.setdefault(k, "")
        return d
    except Exception as e:
        return {"oem": "", "modell": "", "anwendung": "", "hmi_typ": "unklar",
                "sprache": "", "reason": f"fehler:{type(e).__name__}"}


def default_resolver(cfg):
    from .text_harvester import SerpTextSearcher, source_score
    searcher = SerpTextSearcher(cfg)

    def _resolve(oem, modell):
        if not oem:
            return None
        for res in searcher.search(f"{oem} {modell} Steuerung control", n=6):
            u = res.get("url", "")
            if u and not is_dealer(u) and source_score(u) >= 3:
                return u
        return None
    return _resolve


def run(cfg, manifest_path="agent6_image_candidates.json",
        out_csv="agent6_enriched.csv", limit=None,
        fetcher=None, enricher=None, resolver=None, airtable=None, resolve_oem=True) -> dict:
    fetcher = fetcher or fetch_page_text
    client = _client()
    enrich_fn = enricher or (lambda text, url, pat: enrich(text, url, pat, cfg, client))
    resolve_fn = resolver if resolver is not None else (default_resolver(cfg) if resolve_oem else None)
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
                       "fusspedal": 0, "unklar": 0, "final": 0, "airtable_updated": 0}
    for c in uniq:
        if limit and stats["enriched"] >= limit:
            break
        page = c.get("page") or c.get("url")
        d = enrich_fn(fetcher(page) if page else "", c.get("url", ""), c.get("pattern", ""))
        stats["enriched"] += 1
        if d.get("hmi_typ") == "unklar" and page and is_dealer(page) and resolve_fn:
            oem_url = resolve_fn(d.get("oem", ""), d.get("modell", ""))
            if oem_url:
                d2 = enrich_fn(fetcher(oem_url), c.get("url", ""), c.get("pattern", ""))
                if d2.get("hmi_typ") != "unklar":
                    d, page = d2, oem_url
                    stats["oem_nachgeladen"] += 1
        rows.append({"pattern": c.get("pattern", ""), "oem": d.get("oem", ""),
                     "modell": d.get("modell", ""), "anwendung": d.get("anwendung", ""),
                     "hmi_typ": d.get("hmi_typ", "unklar"), "sprache": d.get("sprache", ""),
                     "reason": d.get("reason", ""), "bild_url": c.get("url", ""),
                     "quell_seite": page, "harvested_at": datetime.date.today().isoformat()})

    best = {}
    for r in rows:
        key = (r["oem"].strip().lower(), r["modell"].strip().lower())
        if key == ("", ""):
            best[id(r)] = r
            continue
        if key not in best or (best[key]["hmi_typ"] == "unklar" and r["hmi_typ"] != "unklar"):
            best[key] = r
    final = list(best.values())
    for r in final:
        stats[_bucket(r["hmi_typ"])] += 1
    stats["final"] = len(final)

    _write_csv(final, out_csv)
    json.dump(final, open(out_csv.replace(".csv", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if airtable and getattr(airtable, "enabled", False):
        stats["airtable_updated"] = airtable.update_enrichment(final)
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
    cols = ["pattern", "oem", "modell", "anwendung", "hmi_typ", "sprache",
            "reason", "bild_url", "quell_seite", "harvested_at"]
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
    ap.add_argument("--out", default="agent6_enriched.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-resolve", dest="no_resolve", action="store_true",
                    help="OEM-Seite bei Händlerquellen NICHT nachladen")
    ap.add_argument("--airtable", action="store_true", help="Ergebnisse zurück in Airtable schreiben")
    args = ap.parse_args()
    cfg = load_config(args.config)
    at = None
    if args.airtable:
        from .image_search_harvester import AirtableWriter
        at = AirtableWriter(cfg=cfg)
    res = run(cfg, manifest_path=args.manifest, out_csv=args.out, limit=args.limit,
              airtable=at, resolve_oem=not args.no_resolve)
    print("HMI-ANREICHERUNG:", res)


if __name__ == "__main__":
    main()
