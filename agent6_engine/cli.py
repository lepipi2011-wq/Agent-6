"""Einstiegspunkt: python -m agent6_engine.cli --config config.yaml

Liest Master -> Seeds + Pattern-DB + Bildsuche-Regeln, erntet je Pattern (Klasse),
fügt Hard-Negatives als out_scope hinzu, dedupliziert, meldet Quality-Gate.
"""
from __future__ import annotations
import argparse, os
from collections import Counter

from .config import load_config
from . import master_io as M
from . import harvest_rules as R
from . import image_harvest as H
from . import quality_gate as QG


def _filter_seeds(seeds, cfg):
    countries = set(c.upper() for c in cfg["harvest"]["countries"])
    pats = set(cfg["harvest"]["patterns"])
    out = []
    for s in seeds:
        if countries and (s.land or "").upper() not in countries:
            continue
        if pats and (s.pattern not in pats):
            continue
        out.append(s)
    if cfg["harvest"]["max_oems"]:
        out = out[: cfg["harvest"]["max_oems"]]
    return out


def run(config_path, hypothesis):
    cfg = load_config(config_path)
    print(f"== Agent 6 Image Harvester == DRY_RUN={cfg['harvest']['dry_run']}")
    wb = M.open_master(cfg)
    patterns = M.read_patterns(wb, cfg)
    rules = R.read_rules(wb, cfg)
    seeds = M.read_seeds(wb, cfg, patterns)
    wb.close()

    print(f"Seeds (OEMs): {len(seeds)} | Patterns in DB: {len(patterns)}")
    print(f"Ausschluss-Keywords: {rules.exclusion_keywords}")
    print(f"Kabel-Pflicht-Patterns: {rules.cable_keyword_patterns}")
    print(f"Text-only-Patterns (Bildsuche übersprungen): {rules.text_only_patterns}")
    with_pat = sum(1 for s in seeds if s.pattern)
    with_dom = sum(1 for s in seeds if s.domain)
    print(f"Seeds mit Pattern: {with_pat} | mit OEM-Domain (für OEM-direkt): {with_dom}")

    seeds = _filter_seeds(seeds, cfg)
    print(f"Nach Filter (Land/Pattern/Limit): {len(seeds)} Seeds")

    stats = H.new_stats()

    # In-scope: je OEM unter seiner (normalisierten) Pattern-Klasse
    norm_on = cfg["harvest"].get("normalize_classes", True)
    per_class = Counter()
    for s in seeds:
        cls = M.normalize_class(s.pattern) if norm_on else (s.pattern or "unknown")
        got = H.harvest_oem(s, cls, cfg, rules, patterns, stats)
        per_class[cls] += got

    # Hard-Negatives als out_scope
    if cfg["hard_negatives"]["enabled"]:
        for hn in cfg["hard_negatives"]["seeds"]:
            seed = M.Seed(oem=hn["oem"], pattern=None, segment=hn.get("note"),
                          land=None, domain=M._domain(hn.get("url")) if hn.get("url") else None,
                          link=hn.get("url"), row=-1)
            got = H.harvest_oem(seed, "out_scope", cfg, rules, patterns, stats)
            per_class["out_scope"] += got

    # pHash-Dedup über den geernteten Korpus
    H.phash_dedup(os.path.join(cfg["output"]["dir"], "raw"),
                  cfg["dedup"]["phash_threshold"], stats)

    print("\nBilder je Klasse:", dict(per_class.most_common()))
    QG.evaluate(stats, cfg["quality_gate"], hypothesis)
    sp = os.path.join(cfg["output"]["dir"], cfg["output"]["sources_csv"])
    print(f"\nProvenienz: {sp}")
    print("Nächster Schritt: grouped-OEM-Split + Scope-Gate-Training (Teil B des Notebooks).")
    return stats


def main():
    ap = argparse.ArgumentParser(description="Agent 6 OEM-direct image harvester")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--hypothesis", default="OEM-direkte Produktseiten liefern klassenreine Bilder über Schwelle")
    ap.add_argument("--live", action="store_true", help="DRY_RUN aus (echte Downloads/API)")
    ap.add_argument("--max-oems", type=int, default=None)
    args = ap.parse_args()
    cfg_override = {}
    if args.live or args.max_oems is not None:
        # leichte CLI-Overrides ohne config.yaml zu ändern
        from .config import load_config as _lc
        cfg = _lc(args.config)
        if args.live:
            cfg["harvest"]["dry_run"] = False
        if args.max_oems is not None:
            cfg["harvest"]["max_oems"] = args.max_oems
        # temporär schreiben? -> stattdessen direkt run mit cfg
        return _run_with_cfg(cfg, args.hypothesis)
    run(args.config, args.hypothesis)


def _run_with_cfg(cfg, hypothesis):
    # Variante von run() mit bereits geladener cfg (für CLI-Overrides)
    print(f"== Agent 6 Image Harvester == DRY_RUN={cfg['harvest']['dry_run']}")
    wb = M.open_master(cfg)
    patterns = M.read_patterns(wb, cfg); rules = R.read_rules(wb, cfg)
    seeds = M.read_seeds(wb, cfg, patterns); wb.close()
    seeds = _filter_seeds(seeds, cfg)
    norm_on = cfg["harvest"].get("normalize_classes", True)
    stats = H.new_stats(); per_class = Counter()
    for s in seeds:
        cls = M.normalize_class(s.pattern) if norm_on else (s.pattern or "unknown")
        per_class[cls] += H.harvest_oem(s, cls, cfg, rules, patterns, stats)
    if cfg["hard_negatives"]["enabled"]:
        for hn in cfg["hard_negatives"]["seeds"]:
            seed = M.Seed(oem=hn["oem"], pattern=None, segment=hn.get("note"), land=None,
                          domain=M._domain(hn.get("url")) if hn.get("url") else None,
                          link=hn.get("url"), row=-1)
            per_class["out_scope"] += H.harvest_oem(seed, "out_scope", cfg, rules, patterns, stats)
    H.phash_dedup(os.path.join(cfg["output"]["dir"], "raw"), cfg["dedup"]["phash_threshold"], stats)
    print("\nBilder je Klasse:", dict(per_class.most_common()))
    QG.evaluate(stats, cfg["quality_gate"], hypothesis)
    return stats


if __name__ == "__main__":
    main()
