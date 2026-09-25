"""Konfiguration laden (YAML) mit robusten Defaults."""
from __future__ import annotations
import os, copy

DEFAULTS = {
    "master": {"path": "./agent6_master_live.xlsx",
               "main_sheet": "Agent 6 — Crawler OEM",
               "pattern_sheet": "Pattern DB",
               "bildsuche_sheet": "Bildsuche-Training",
               "header_row": 2, "pattern_header_row": 4, "bildsuche_header_row": 2},
    "output": {"dir": "./out/scopegate", "sources_csv": "sources.csv",
               "filename_pattern": "{cls}__{oem}__{idx}.jpg"},
    "harvest": {"dry_run": True, "images_per_oem": 12, "oem_direct_first": True,
                "max_pages_per_site": 6, "countries": [], "patterns": [], "max_oems": 0,
                "normalize_classes": True,
                "resume": True,
                "vlm_filter": False, "min_image_px": 300, "max_image_px": 6000,
                "vlm_model": "claude-haiku-4-5-20251001",
                "request_timeout": 15,
                "user_agent": "Agent6-ImageHarvester/1.0 (research; respects robots)",
                "respect_robots": True},
    "dedup": {"phash_threshold": 6},
    "source_score": {"oem_direct": 3, "press": 2, "image_search": 1},
    "quality_gate": {"yield_min": 0.30, "oem_direct_min": 0.40, "score_min": 2.0},
    "search": {"provider": "serpapi", "serpapi_env": "SERPAPI_KEY", "results_per_query": 8},
    "hard_negatives": {"enabled": True, "seeds": []},
    "database": {"url": "sqlite:///agent6.db"},
}


def _deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> dict:
    # .env laden (falls vorhanden), damit API-Keys als Umgebungsvariablen bereitstehen.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    user = {}
    if path and os.path.exists(path):
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
        except Exception as e:  # pragma: no cover
            print(f"WARN: config.yaml nicht ladbar ({e}); nutze Defaults.")
    return _deep_merge(DEFAULTS, user)
