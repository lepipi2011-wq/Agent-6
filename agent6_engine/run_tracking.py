"""Run-Tracking — macht Läufe unterscheidbar (Prämissen/Regeländerungen nachvollziehbar).

Drei Bausteine (siehe DOMAIN_RULES R9 / STATUS):
1. Jeder Lauf bekommt eine RUN_ID + eine REGEL_VERSION (Prämissen-Stand) + den Git-Commit.
2. Jeder Review-Record wird am Ende mit Run-ID/Regel-Version gestempelt (AirtableWriter.stamp_run).
3. Vor dem Schreiben wird der aktuelle Review-Stand als datierter Snapshot ins Repo gelegt
   (runs/), damit Vorher/Nachher vergleichbar bleibt — ohne das 1000-Record-Limit zu sprengen.

Reiner, offline testbarer Kern; kein Airtable-Import.
"""
from __future__ import annotations
import os, json, datetime, subprocess

# Prämissen-Stand. BEI JEDER Regeländerung hochzählen + Kurzbeschreibung anpassen.
REGEL_VERSION = "v3.2"
REGEL_BESCHREIBUNG = "CAN=Pflicht, No-Can=out, SIL-Ausschluss, Bild=Betriebsschnittstelle, Trust vor Volumen"


def new_run_id(now=None) -> str:
    """Filename-sichere, sortierbare Run-ID: '20260928-1430-v3.2'."""
    now = now or datetime.datetime.now()
    return f"{now:%Y%m%d-%H%M}-{REGEL_VERSION}"


def git_commit(cwd=None) -> str:
    """Kurzer Commit-SHA des Repos, best-effort (leer, wenn kein Git/Fehler)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def snapshot_review(records, run_id, out_dir="runs", suffix="before") -> str:
    """Schreibt den aktuellen Review-Stand als JSON-Snapshot ins Repo und gibt den Pfad zurück.
    records: Liste der aus Airtable geladenen Record-dicts (oder beliebige serialisierbare Zeilen)."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"review_{run_id}_{suffix}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_id": run_id, "regel_version": REGEL_VERSION, "suffix": suffix,
                   "count": len(records or []), "records": records or []},
                  f, ensure_ascii=False, indent=1)
    return path


def run_summary(run_id, n_records, query_set="", metrics=None, commit=None, notiz="") -> dict:
    """Baut die Zusammenfassungs-Zeile für die Airtable-'Runs'-Tabelle + den lokalen Run-Log."""
    m = metrics or {}
    return {
        "Run-ID": run_id,
        "Datum": datetime.date.today().isoformat(),
        "Regel-Version": f"{REGEL_VERSION} — {REGEL_BESCHREIBUNG}",
        "Commit": commit if commit is not None else git_commit(),
        "Query-Set": query_set,
        "Records": n_records,
        "Recall": m.get("recall"),
        "Precision": m.get("precision"),
        "Yield": m.get("yield"),
        "Notiz": notiz,
    }


def write_run_log(summary, out_dir="runs") -> str:
    """Lokaler, git-getrackter Run-Log (eine JSON je Lauf) — Audit-Trail unabhängig von Airtable."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"run_{summary.get('Run-ID','unknown')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return path
