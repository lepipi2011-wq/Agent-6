"""Pipeline-CLI — die Installations-/Betriebs-Abfolge als Ein-Zeilen-Befehle.

  python -m agent6_engine.pipeline init      # DB-Schema anlegen
  python -m agent6_engine.pipeline import    # Master -> DB (Orgs, Patterns, Claims)
  python -m agent6_engine.pipeline enrich    # Konnektoren -> LEI/VAT + sicheres Re-Merge
  python -m agent6_engine.pipeline review    # Merge-Entscheidungen aus xlsx zurückspielen
  python -m agent6_engine.pipeline export    # Master-Sicht + Merge-Review als xlsx
  python -m agent6_engine.pipeline status    # Kennzahlen
  python -m agent6_engine.pipeline all       # init+import+enrich+export in Folge

Alle lesen config.yaml (master.path, database.url).
"""
from __future__ import annotations
import argparse
from sqlalchemy import select, func
from .config import load_config
from . import db as DB
from . import db_import, db_export, enrich_keys, review_apply
from .db import Organization, MergeCandidate, Claim


def _session(cfg):
    eng = DB.make_engine(cfg["database"]["url"])
    return DB.init_db(eng)()


def cmd_init(cfg, args):
    eng = DB.make_engine(cfg["database"]["url"])
    DB.Base.metadata.create_all(eng)
    print(f"DB initialisiert: {cfg['database']['url']}")


def cmd_import(cfg, args):
    s = _session(cfg)
    print("IMPORT:", db_import.import_master(s, cfg))
    s.close()


def cmd_enrich(cfg, args):
    s = _session(cfg)
    conns = [] if args.dry else None
    if args.dry:
        print("(--dry: keine externen Aufrufe; nur Re-Resolve über vorhandene Schlüssel)")
    enrich_keys.run(s, connectors=conns, limit=args.limit, live=not args.dry, region=args.region)
    s.close()


def cmd_review(cfg, args):
    s = _session(cfg)
    path = args.file or "agent6_merge_review.xlsx"
    print("REVIEW:", review_apply.apply_review(s, path))
    s.close()


def cmd_export(cfg, args):
    s = _session(cfg)
    m = db_export.export_master(s, "agent6_export.xlsx")
    r = db_export.export_merge_review(s, "agent6_merge_review.xlsx")
    print("Export:", m, "|", r)
    s.close()


def cmd_status(cfg, args):
    s = _session(cfg)
    orgs = s.scalar(select(func.count(Organization.id)))
    with_lei = s.scalar(select(func.count(Organization.id)).where(Organization.lei.is_not(None)))
    claims = s.scalar(select(func.count(Claim.id)))
    pending = s.scalar(select(func.count(MergeCandidate.id)).where(MergeCandidate.decision == "pending"))
    print(f"Organisationen: {orgs} | mit LEI: {with_lei} | Claims: {claims} | Review offen: {pending}")
    s.close()


def cmd_all(cfg, args):
    print("== all: init -> import -> enrich -> export ==")
    cmd_init(cfg, args)
    cmd_import(cfg, args)
    cmd_enrich(cfg, args)
    cmd_export(cfg, args)
    cmd_status(cfg, args)


def cmd_discover(cfg, args):
    s = _session(cfg)
    from . import discovery, master_io
    wb = master_io.open_master(cfg)
    patterns = master_io.read_patterns(wb, cfg)
    only = [p.strip() for p in args.patterns.split(",")] if args.patterns else None
    res = discovery.discover(s, cfg, patterns, per_pattern=args.per_pattern,
                             only_patterns=only)
    print("DISCOVER:", res)
    if res.get("quality_warning"):
        print("  ⚠ QUALITÄT:", res["quality_warning"])
    s.close()


def main():
    ap = argparse.ArgumentParser(description="Agent 6 Pipeline")
    ap.add_argument("command", choices=["init", "import", "enrich", "review", "export",
                                        "status", "all", "discover"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--region", default="eu", choices=["eu", "us"])
    ap.add_argument("--file", default=None, help="xlsx für 'review'")
    ap.add_argument("--patterns", default=None, help="Discovery: nur diese Codes, z.B. P4,P5")
    ap.add_argument("--per-pattern", dest="per_pattern", type=int, default=8)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    {"init": cmd_init, "import": cmd_import, "enrich": cmd_enrich, "review": cmd_review,
     "export": cmd_export, "status": cmd_status, "all": cmd_all,
     "discover": cmd_discover}[args.command](cfg, args)


if __name__ == "__main__":
    main()
