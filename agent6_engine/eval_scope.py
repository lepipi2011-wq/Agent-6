"""Eval-Harness — misst die Scope-Urteilsschicht gegen die menschlichen Review-Verdikte.

Zweck: Die menschlichen Verdikte in Airtable (Feld 'Verdikt') sind das Goldset. Dieses Modul
vergleicht das maschinelle 'Claude-Urteil' dagegen und berechnet Recall/Precision der
ZIEL-Erkennung. Damit wird jede Prompt-/Code-Aenderung messbar statt Bauchgefuehl.

ZIEL-Definition (Pierre-Regeln): ein Record ist ein ZIEL, wenn der Mensch ihn als
'In-Scope' ODER 'No Can' (Anwendung passt, nur CAN fehlt -> Aktuator-Retrofit) eingestuft hat.
KEIN-ZIEL: 'Funksteuerung' (schon RC = Verdraengung), 'Kein Objekt/unbrauchbar', 'Out of scope',
'Rad', 'Autonomous'. 'Unsicher'/leer werden fuer die harte Metrik IGNORIERT (kein Goldwert).

Vorhersage: Claude-Urteil 'In-Scope' = positiv (ZIEL), sonst negativ.

Kern (score/normalisieren) ist rein und offline testbar; main() zieht die Records aus Airtable.
"""
from __future__ import annotations
import os, sys, json, argparse

# --- Klassifikation der menschlichen Verdikte (robust gegen Symbole/Gross-Klein) ---
_ZIEL_KEYS = ("in-scope", "in scope", "no can", "nocan")
_KEIN_KEYS = ("funksteuerung", "kein objekt", "unbrauchbar", "out of scope", "out-of-scope",
              "rad", "autonom")  # 'autonom' faengt Autonomous
_IGNORE_KEYS = ("unsicher",)


def gold_label(verdikt) -> str | None:
    """'ZIEL' / 'KEIN' / None (ignorieren: Unsicher/leer/unbekannt)."""
    if not verdikt:
        return None
    s = str(verdikt).strip().lower()
    if any(k in s for k in _IGNORE_KEYS):
        return None
    if any(k in s for k in _ZIEL_KEYS):
        return "ZIEL"
    if any(k in s for k in _KEIN_KEYS):
        return "KEIN"
    return None


def pred_label(claude_urteil) -> str:
    """Vorhersage aus dem maschinellen Urteil: 'In-Scope' -> ZIEL, alles andere -> KEIN."""
    s = str(claude_urteil or "").strip().lower()
    return "ZIEL" if ("in-scope" in s or "in scope" in s) else "KEIN"


def score(pairs) -> dict:
    """pairs: Iterable von (verdikt, claude_urteil). Gibt Kennzahlen der ZIEL-Erkennung zurueck.
    Nur Records mit gueltigem Goldwert (ZIEL/KEIN) zaehlen."""
    tp = fp = fn = tn = 0
    ignoriert = 0
    for verdikt, urteil in pairs:
        g = gold_label(verdikt)
        if g is None:
            ignoriert += 1
            continue
        p = pred_label(urteil)
        if g == "ZIEL" and p == "ZIEL":
            tp += 1
        elif g == "ZIEL" and p == "KEIN":
            fn += 1
        elif g == "KEIN" and p == "ZIEL":
            fp += 1
        else:
            tn += 1
    ziele = tp + fn
    vorhergesagt_ziel = tp + fp
    recall = tp / ziele if ziele else 0.0
    precision = tp / vorhergesagt_ziel if vorhergesagt_ziel else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "ziele": ziele,
            "recall": recall, "precision": precision, "f1": f1,
            "bewertet": tp + fp + fn + tn, "ignoriert": ignoriert}


def scorecard(m: dict) -> str:
    return (
        "=== Scope-Eval (Claude-Urteil vs. Mensch-Verdikt) ===\n"
        f"  Bewertete Records:   {m['bewertet']}  (ignoriert/Unsicher/leer: {m['ignoriert']})\n"
        f"  Echte Ziele (Gold):  {m['ziele']}\n"
        f"  RECALL  (Ziele gefunden):   {m['recall']*100:5.1f} %   ({m['tp']} von {m['ziele']})\n"
        f"  PRECISION (Ziel-Treffer ok): {m['precision']*100:5.1f} %   ({m['tp']} von {m['tp']+m['fp']})\n"
        f"  F1:                          {m['f1']*100:5.1f} %\n"
        f"  Konfusion:  TP={m['tp']}  FN={m['fn']} (echte Ziele verworfen!)  "
        f"FP={m['fp']}  TN={m['tn']}\n"
    )


def _pairs_from_records(records, verdikt_fid, urteil_fid):
    for r in records:
        c = r.get("cellValuesByFieldId", r.get("fields", {}))
        def _v(fid_or_name):
            v = c.get(fid_or_name)
            if isinstance(v, dict):
                return v.get("name")
            return v
        yield _v(verdikt_fid), _v(urteil_fid)


def _pairs_from_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield (row.get("Verdikt") or row.get("verdikt"),
                   row.get("Claude-Urteil") or row.get("claude_urteil"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scope-Eval gegen Review-Goldset")
    ap.add_argument("--json", action="append", default=[],
                    help="Airtable-JSON-Dump (kann mehrfach angegeben werden)")
    ap.add_argument("--csv", default=None, help="CSV mit Spalten Verdikt, Claude-Urteil")
    ap.add_argument("--verdikt-fid", default="fldJmXTrLqBSMhf4a")
    ap.add_argument("--urteil-fid", default="fldDK87aKBB9B9s3Q")
    args = ap.parse_args(argv)

    pairs = []
    for jp in args.json:
        data = json.load(open(jp, encoding="utf-8"))
        recs = data["records"] if isinstance(data, dict) else data
        pairs += list(_pairs_from_records(recs, args.verdikt_fid, args.urteil_fid))
    if args.csv:
        pairs += list(_pairs_from_csv(args.csv))
    if not pairs:
        print("Keine Daten. --json <dump> oder --csv <datei> angeben.", file=sys.stderr)
        return 2
    print(scorecard(score(pairs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
