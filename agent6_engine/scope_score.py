"""Scope-Score — Claude gibt ein eigenes Urteil ab, das gegen die Mensch-Verdikte
gemessen wird. So sieht man, ob das System mitlernt (Weg 1: In-Context-Lernen).

Drei Bausteine:
1. normalize_verdikt(): die Verdikt-Werte des Teams -> vier saubere Klassen.
2. build_lessons(): aus bestaetigten Verdikten Lehrbeispiele bauen, die in den
   Anreicherungs-Prompt gelegt werden (Claude lernt aus den Faellen, wo das Team
   entschieden hat — besonders aus Fehlern).
3. evaluate(): Claude-Urteil vs. Mensch-Verdikt -> Trefferquote gesamt + je Pattern.
   Das ist der Lern-Monitor: steigt die Quote ueber die Laeufe, lernt das System mit.

WICHTIG (ehrlich): Das LLM selbst wird dabei NICHT umtrainiert (Gewichte bleiben fix).
Das "Lernen" liegt in den Beispielen, die aus euren Verdikten in den Prompt wandern.
Der nachhaltige Weg bleibt ein eigenes Modell aus den gesammelten Labels.
"""
from __future__ import annotations
import csv, re, json

KLASSEN = ("In-Scope", "Out-of-Scope", "Unsicher", "Kein Objekt")


def normalize_verdikt(raw) -> str:
    """Verdikt-Werte des Teams (mit Emoji/Varianten) -> eine der vier Klassen."""
    t = str(raw or "").strip().lower()
    if not t:
        return ""
    if "kein objekt" in t or "unbrauchbar" in t:
        return "Kein Objekt"
    if "out" in t or "rad" in t or "raus" in t or "ausser" in t or "außer" in t:
        return "Out-of-Scope"
    if "unsicher" in t or "unklar" in t or "?" in t:
        return "Unsicher"
    if "in-scope" in t or "in scope" in t or "✓" in t or "ja" == t:
        return "In-Scope"
    return ""


def _norm_key(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def build_lessons(rows, max_examples=12) -> str:
    """Baut Lehrbeispiele aus bestaetigten Verdikten. Ausgewogen In/Out, damit
    Claude beide Seiten sieht. rows: dicts mit oem/anwendung/pattern/verdikt(+notiz)."""
    buckets = {"In-Scope": [], "Out-of-Scope": [], "Unsicher": [], "Kein Objekt": []}
    seen = set()
    for r in rows:
        v = normalize_verdikt(r.get("verdikt") or r.get("Verdikt"))
        if v not in buckets:
            continue
        oem = (r.get("oem") or r.get("OEM") or "").strip()
        anw = (r.get("anwendung") or r.get("Anwendungsart") or "").strip()
        pat = (r.get("pattern") or r.get("Pattern-Vorschlag") or "").split()[0] if \
              (r.get("pattern") or r.get("Pattern-Vorschlag")) else ""
        key = _norm_key(f"{oem}|{anw}")
        if key in seen or not (oem or anw):
            continue
        seen.add(key)
        note = (r.get("notiz") or r.get("Notizen") or "").strip()
        buckets[v].append({"oem": oem, "anwendung": anw, "pattern": pat, "verdikt": v, "note": note})

    # ausgewogen ziehen
    per = max(1, max_examples // 3)
    chosen = []
    for v in ("In-Scope", "Out-of-Scope", "Unsicher"):
        chosen.extend(buckets[v][:per])
    if not chosen:
        return ""
    lines = ["\nGELERNTE BEISPIELE (Urteile des Teams — nutze sie als Massstab):"]
    for e in chosen:
        s = f'  - {e["oem"]} / {e["anwendung"]}'
        if e["pattern"]:
            s += f' ({e["pattern"]})'
        s += f' -> {e["verdikt"]}'
        if e["note"]:
            s += f' [{e["note"][:80]}]'
        lines.append(s)
    return "\n".join(lines)


def load_verdikt_rows(path) -> list:
    """Liest die gesicherte Verdikt-CSV (Airtable-Export) oder JSON."""
    if str(path).lower().endswith(".json"):
        return json.load(open(path, encoding="utf-8"))
    return list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))


# ------------------------------------------------------------------ Monitor
def evaluate(rows) -> dict:
    """Vergleicht Claude-Urteil gegen Mensch-Verdikt. rows brauchen die Felder
    'claude_urteil'/'Claude-Urteil' und 'verdikt'/'Verdikt'. Kein-Objekt zaehlt als Out."""
    def collapse(k):                       # fuer Scope-Treffer: Kein Objekt ~ Out
        return "Out-of-Scope" if k == "Kein Objekt" else k

    gesamt = {"n": 0, "treffer": 0}
    per_pattern = {}
    confusion = {}
    for r in rows:
        mensch = normalize_verdikt(r.get("verdikt") or r.get("Verdikt"))
        claude = normalize_verdikt(r.get("claude_urteil") or r.get("Claude-Urteil"))
        if not mensch or not claude:
            continue
        m, c = collapse(mensch), collapse(claude)
        gesamt["n"] += 1
        hit = int(m == c)
        gesamt["treffer"] += hit
        pat = (r.get("pattern") or r.get("Pattern-Vorschlag") or "?").split()[0] \
            if (r.get("pattern") or r.get("Pattern-Vorschlag")) else "?"
        pp = per_pattern.setdefault(pat, {"n": 0, "treffer": 0})
        pp["n"] += 1
        pp["treffer"] += hit
        confusion[(m, c)] = confusion.get((m, c), 0) + 1

    acc = round(gesamt["treffer"] / gesamt["n"], 3) if gesamt["n"] else 0.0
    pp_out = {k: {"n": v["n"], "treffer": v["treffer"],
                  "quote": round(v["treffer"] / v["n"], 3) if v["n"] else 0.0}
              for k, v in sorted(per_pattern.items())}
    return {"n": gesamt["n"], "treffer": gesamt["treffer"], "trefferquote": acc,
            "je_pattern": pp_out,
            "verwechslungen": {f"Mensch={m}|Claude={c}": n for (m, c), n in
                               sorted(confusion.items(), key=lambda x: -x[1]) if m != c}}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Lern-Monitor: Claude-Urteil vs. Mensch-Verdikt")
    ap.add_argument("--review", required=True,
                    help="CSV/JSON mit Spalten Claude-Urteil UND Verdikt (Airtable-Export)")
    args = ap.parse_args()
    rows = load_verdikt_rows(args.review)
    res = evaluate(rows)
    print(f"\nLERN-MONITOR — {res['n']} bewertete Maschinen")
    print(f"  Trefferquote Claude vs. Team: {res['trefferquote']*100:.1f}%  "
          f"({res['treffer']}/{res['n']})")
    if res["je_pattern"]:
        print("\n  Je Pattern:")
        for p, v in res["je_pattern"].items():
            print(f"    {p:5} {v['quote']*100:5.1f}%  ({v['treffer']}/{v['n']})")
    if res["verwechslungen"]:
        print("\n  Haeufigste Verwechslungen:")
        for k, n in list(res["verwechslungen"].items())[:5]:
            print(f"    {k}: {n}")


if __name__ == "__main__":
    main()
