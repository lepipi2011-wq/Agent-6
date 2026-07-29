"""Preis-Recherche — Groessenordnung statt exaktem Preis.

Warum Groessenordnung: B2B-Maschinenhersteller nennen online fast nie einen Listenpreis
("Preis auf Anfrage"). Ziel ist hier nur, die Retrofit-attraktiven Maschinen (>~10k)
von den unattraktiven zu trennen. Dafuer reicht "grob 35k, laut Marktplatz" statt einer
Scheingenauigkeit.

Ablauf je Maschine (OEM+Modell):
1. Gezielte Web-Suche (Gebraucht-/Verkaufsangebote, Marktplaetze).
2. Claude liest die Treffer-Snippets und gibt zurueck:
   - preis_indikation_eur: grobe Zahl in EUR (Mitte der Spanne) oder null
   - preis_spanne: z.B. "25.000-45.000"
   - preis_sicherheit: "belegt" (Marktplatz-Angebot gefunden) / "geschaetzt"
     (nur Klassen-Einordnung) / "unbekannt"
   - preis_quelle: URL des Belegs oder "Klassen-Schaetzung"

Eigener, abschaltbarer Schritt (kostet SerpAPI + Claude pro Maschine).
"""
from __future__ import annotations
import os, csv, json


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def recherche_preis(oem, modell, anwendung, cfg, searcher=None, client=None) -> dict:
    leer = {"preis_indikation_eur": None, "preis_spanne": "", "preis_sicherheit": "unbekannt",
            "preis_quelle": ""}
    if not (oem or modell):
        return leer
    client = client or _client()
    if client is None:
        return leer
    if searcher is None:
        from .text_harvester import SerpTextSearcher
        searcher = SerpTextSearcher(cfg)

    begriff = f"{oem} {modell}".strip()
    treffer = []
    for q in (f"{begriff} price for sale", f"{begriff} gebraucht Preis kaufen"):
        try:
            for res in searcher.search(q, n=5):
                treffer.append({"titel": res.get("title", ""), "snippet": res.get("snippet", ""),
                                "url": res.get("url", "")})
        except Exception:
            pass
    if not treffer:
        return leer

    kontext = "\n".join(f"- {t['titel']} | {t['snippet']} | {t['url']}" for t in treffer[:8])
    model = cfg.get("harvest", {}).get("vlm_model", "claude-haiku-4-5-20251001")
    prompt = (
        f"Maschine: {oem} {modell} ({anwendung}). Unten Web-Treffer (Verkaufs-/Gebrauchtangebote). "
        "Schaetze die PREIS-GROESSENORDNUNG in EUR (keine Scheingenauigkeit). Regeln:\n"
        "- Findest du konkrete Angebote mit Preis: 'belegt', nimm deren Bereich (USD/GBP grob "
        "in EUR umrechnen). preis_quelle = die belegende URL.\n"
        "- Findest du keine konkreten Preise, aber kennst die Maschinenklasse: 'geschaetzt', "
        "gib eine typische Spanne fuer diese Maschinenart/-groesse. preis_quelle='Klassen-Schaetzung'.\n"
        "- Gar keine Einordnung moeglich: 'unbekannt'.\n"
        "preis_indikation_eur = Mitte der Spanne als ganze Zahl.\n\n"
        f"Treffer:\n{kontext}\n\n"
        'Antworte NUR JSON {"preis_indikation_eur","preis_spanne","preis_sicherheit","preis_quelle"}.')
    try:
        msg = client.messages.create(model=model, max_tokens=200,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        a, b = txt.find("{"), txt.rfind("}")
        d = json.loads(txt[a:b + 1]) if a >= 0 and b > a else {}
        return {**leer, **{k: d.get(k, leer[k]) for k in leer}}
    except Exception:
        return leer


def run(cfg, candidates_path="agent6_enriched.csv", out_csv="agent6_preise.csv",
        limit=None, nur_prio=None, searcher=None, client=None, airtable=None) -> dict:
    rows = list(csv.DictReader(open(candidates_path, newline="", encoding="utf-8-sig")))
    stats = {"kandidaten": len(rows), "recherchiert": 0, "belegt": 0, "geschaetzt": 0,
             "unbekannt": 0, "airtable_updated": 0}
    client = client or _client()
    out = []
    for r in rows:
        # ausser-Scope und (optional) nicht-Prioritaeten ueberspringen -> Kosten sparen
        if "AUSSER SCOPE" in (r.get("anwendung") or ""):
            continue
        if nur_prio and (r.get("prioritaet") or "") not in nur_prio:
            continue
        if limit and stats["recherchiert"] >= limit:
            break
        d = recherche_preis(r.get("oem", ""), r.get("modell", ""), r.get("anwendung", ""),
                            cfg, searcher=searcher, client=client)
        stats["recherchiert"] += 1
        stats[d["preis_sicherheit"]] = stats.get(d["preis_sicherheit"], 0) + 1
        rr = dict(r)
        rr.update(d)
        out.append(rr)

    if out:
        cols = list(out[0].keys())
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in out:
                w.writerow(r)
    if airtable and getattr(airtable, "enabled", False):
        stats["airtable_updated"] = airtable.update_fields(
            out, {"Preis-EUR": "preis_indikation_eur", "Preis-Spanne": "preis_spanne",
                  "Preis-Sicherheit": "preis_sicherheit", "Preis-Quelle": "preis_quelle"})
    stats["out_csv"] = out_csv
    return stats


def main():
    import argparse
    from .config import load_config
    ap = argparse.ArgumentParser(description="Preis-Recherche (Groessenordnung) je Maschine")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--candidates", default="agent6_enriched.csv")
    ap.add_argument("--out", default="agent6_preise.csv")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--nur-prio", dest="nur_prio", default=None,
                    help="nur diese Prioritaeten recherchieren, z.B. A,B (spart Kosten)")
    ap.add_argument("--airtable", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    at = None
    if args.airtable:
        from .image_search_harvester import AirtableWriter
        at = AirtableWriter(cfg=cfg)
    nur = set(args.nur_prio.split(",")) if args.nur_prio else None
    res = run(cfg, candidates_path=args.candidates, out_csv=args.out, limit=args.limit,
              nur_prio=nur, airtable=at)
    print("PREIS-RECHERCHE:", res)


if __name__ == "__main__":
    main()
