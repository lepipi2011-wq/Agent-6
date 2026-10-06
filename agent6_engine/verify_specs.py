"""Spec-Verifikation — CAN / Gewicht / Leistung / SIL gründlich am DATENBLATT prüfen.

Warum: CAN ist Pflichtkriterium (DOMAIN_RULES R3), lässt sich aber NICHT aus dem Bild lesen.
Diese Stufe sucht aktiv die Datenblatt-/Spec-Seite eines Records, extrahiert CAN/Gewicht/Leistung/SIL
MIT Textbeleg, berechnet die Priorität neu und schreibt alles inkl. Quell-Link nach Airtable zurück.

Injizierbar (searcher/fetcher/client) -> offline testbar. Kein Key -> definierte 'unklar'-Defaults.
"""
from __future__ import annotations
import os, re, json, argparse

from . import hmi_enrichment as H

_CAN_HINT = ("CAN belegt (CAN/CANopen/J1939 direkt), 'wahrscheinlich CAN' (IQAN/Danfoss/BODAS/E-Hydraulik), "
            "'wahrscheinlich rein-hydraulisch' (Gegen-Anker), 'unklar' (nichts im Text)")


def _pick_spec_url(oem, results):
    """Bestes Suchergebnis für ein Datenblatt: OEM-eigene Domain + 'datasheet/spec/pdf' bevorzugt."""
    if not results:
        return None
    oem_tok = H.norm_oem(oem).split(" ")[0] if oem else ""

    def score(r):
        u = (r.get("url") or "").lower()
        t = (r.get("title", "") + " " + r.get("snippet", "")).lower()
        s = 0
        if oem_tok and oem_tok in u:
            s += 3                         # OEM-eigene Domain
        if u.endswith(".pdf") or "datasheet" in u or "spec" in u or "technische-daten" in t or "specification" in t:
            s += 2
        if H._trust.is_low_trust(u):
            s -= 5                         # Aggregator/Social abwerten
        return s
    return sorted(results, key=score, reverse=True)[0].get("url")


def extract_specs(oem, modell, page_text, cfg=None, client=None) -> dict:
    """Extrahiert Specs aus dem Datenblatt-Text. Reiner Parser um EINEN Claude-Aufruf."""
    d = {"can_bus": "unklar", "can_reason": "", "gewicht_t": None, "leistung_kw": None,
         "groesse_beleg": "", "sil_pflicht": "unklar", "sil_beleg": ""}
    client = client or H._client()
    if client is None or not (page_text or "").strip():
        d["can_reason"] = "kein-key-oder-text"
        return d
    model = (cfg or {}).get("harvest", {}).get("vlm_model", "claude-haiku-4-5-20251001")
    prompt = (
        f"Datenblatt/Spec-Text zu OEM '{oem}', Modell '{modell}'. Extrahiere NUR belegte Fakten:\n"
        f"- can_bus: {_CAN_HINT}\n"
        "- can_reason: Textstelle zu can_bus\n"
        "- gewicht_t: Betriebsgewicht in Tonnen als ZAHL (kg/lbs umrechnen), sonst null\n"
        "- leistung_kw: Motorleistung in kW als ZAHL (HP/PS: 1 HP=0.75 kW), sonst null\n"
        "- groesse_beleg: Originalangabe zu Gewicht/Leistung\n"
        "- sil_pflicht: 'ja' wenn SIL/SIL2/PL d/EN ISO 13849/functional safety/Personentransport belegt, sonst 'nein'/'unklar'\n"
        "- sil_beleg: Textstelle zu SIL\n"
        "Rate NICHT. Steht etwas nicht im Text -> 'unklar' bzw. null.\n\n"
        f"Text:\n{(page_text or '')[:9000]}\n\n"
        'Antworte NUR JSON {"can_bus","can_reason","gewicht_t","leistung_kw","groesse_beleg","sil_pflicht","sil_beleg"}.')
    try:
        msg = client.messages.create(model=model, max_tokens=400,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        got = H._parse_json(txt)
        for k in d:
            if got.get(k) not in (None, ""):
                d[k] = got[k]
    except Exception as e:
        d["can_reason"] = f"fehler:{type(e).__name__}"
    return d


def verify_one(rec, cfg=None, searcher=None, fetcher=None, client=None) -> dict:
    """Sucht das Datenblatt zu einem Record und extrahiert die Specs. rec braucht oem/modell (+bild_url)."""
    oem = (rec.get("oem") or "").strip()
    modell = (rec.get("modell") or "").strip()
    if not oem:
        return {"skipped": "kein-oem"}
    q = f"{oem} {modell} datasheet technical specifications CAN weight kW".strip()
    results = searcher.search(q, n=8) if searcher else []
    spec_url = _pick_spec_url(oem, results)
    text = (fetcher(spec_url) if (fetcher and spec_url) else "") or ""
    specs = extract_specs(oem, modell, text, cfg, client)
    specs["spec_url"] = spec_url or ""
    return specs


def run_verify(records, cfg=None, searcher=None, fetcher=None, client=None, airtable=None, limit=None) -> dict:
    cfg = cfg or {}
    searcher = searcher if searcher is not None else _default_searcher(cfg)
    fetcher = fetcher or H.fetch_deep
    client = client if client is not None else H._client()
    stats = {"geprueft": 0, "can_geklaert": 0, "sil_geklaert": 0, "uebersprungen": 0, "airtable_updated": 0}
    out = []
    for rec in (records[:limit] if limit else records):
        specs = verify_one(rec, cfg, searcher, fetcher, client)
        if specs.get("skipped"):
            stats["uebersprungen"] += 1
            continue
        stats["geprueft"] += 1
        gstat = H.groesse_status(specs.get("gewicht_t"), specs.get("leistung_kw"))
        prio = H.priorisiere(specs.get("can_bus", "unklar"), rec.get("preis_eur"),
                             rec.get("hmi_typ", "unklar"), rec.get("ist_zielmaschine", True),
                             rec.get("claude_urteil", ""), gstat, specs.get("sil_pflicht", "unklar"),
                             rec.get("verdikt", ""))
        if specs.get("can_bus") not in (None, "", "unklar"):
            stats["can_geklaert"] += 1
        if specs.get("sil_pflicht") not in (None, "", "unklar"):
            stats["sil_geklaert"] += 1
        out.append({"bild_url": rec.get("bild_url"),
                    "can_bus": specs.get("can_bus", "unklar"), "can_reason": specs.get("can_reason", ""),
                    "gewicht_t": ("" if specs.get("gewicht_t") in (None, "") else str(specs.get("gewicht_t"))),
                    "leistung_kw": ("" if specs.get("leistung_kw") in (None, "") else str(specs.get("leistung_kw"))),
                    "groesse_status": gstat, "sil_pflicht": specs.get("sil_pflicht", "unklar"),
                    "sil_beleg": specs.get("sil_beleg", ""), "spec_url": specs.get("spec_url", ""),
                    "prioritaet": prio})
    if airtable and getattr(airtable, "enabled", False) and out:
        stats["airtable_updated"] = airtable.update_fields(out, {
            "CAN-Bus": "can_bus", "Gewicht-t": "gewicht_t", "Leistung-kW": "leistung_kw",
            "Größe-Status": "groesse_status", "SIL-Pflicht": "sil_pflicht",
            "Spec-Quelle": "spec_url", "Priorität": "prioritaet"})
        stats["airtable_failed"] = getattr(airtable, "write_failures", 0)
    stats["rows"] = len(out)
    return stats


def _default_searcher(cfg):
    try:
        from .text_harvester import SerpTextSearcher
        return SerpTextSearcher(cfg)
    except Exception:
        return None


def main(argv=None):
    from .config import load_config
    from .image_search_harvester import AirtableWriter
    ap = argparse.ArgumentParser(description="Spec-Verifikation (CAN/Gewicht/Leistung/SIL am Datenblatt)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--from-airtable", dest="from_airtable", action="store_true")
    ap.add_argument("--only-unklar", dest="only_unklar", action="store_true",
                    help="nur Records mit CAN-Bus leer/unklar verifizieren (spart Aufrufe)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--airtable", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    writer = AirtableWriter(cfg=cfg) if args.airtable or args.from_airtable else None
    records = []
    if args.from_airtable and writer:
        for rec in writer._all_records():
            f = rec.get("fields", {})
            can = (f.get("CAN-Bus") or "").strip().lower()
            if args.only_unklar and can and can != "unklar":
                continue
            records.append({"oem": f.get("OEM", ""), "modell": f.get("Modell", ""),
                            "bild_url": f.get("Bild-URL", ""), "hmi_typ": f.get("HMI-Typ", "unklar"),
                            "claude_urteil": f.get("Claude-Urteil", ""), "preis_eur": None,
                            "ist_zielmaschine": True, "verdikt": f.get("Verdikt", "")})
    stats = run_verify(records, cfg, airtable=(writer if args.airtable else None), limit=args.limit)
    print("VERIFY-SPECS:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
