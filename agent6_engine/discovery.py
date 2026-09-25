"""Discovery — NEUE OEM-Kandidaten für bestehende Patterns finden.

Ablauf je Pattern: Suche (SerpApi) -> Kandidaten extrahieren -> gegen bestehende
DB deduplizieren -> VLM-Scope-Gate (in-scope? richtiges Pattern?) -> Quality-Gate
-> Überlebende als 'candidate'-Orgs schreiben (fließen dann durch enrich/verify/review).

WICHTIG (Methodik): Discovery ist die riskanteste Betriebsart. Ohne VLM-Gate +
Quality-Gate produziert man Volumen statt Prospects. Beide sind hier zwingend.

Retrieval (SerpApi) und VLM laufen auf deiner Maschine (Keys nötig). Die Logik
(Extraktion, Dedup, Gate-Verdrahtung, Quality-Gate) ist per Injection offline testbar.
"""
from __future__ import annotations
import os
from urllib.parse import urlparse
from .db import Organization, Claim
from .entity_resolution import classify, upsert_org
from . import vlm_filter


# ---------------------------------------------------------------- Retrieval
class SerpapiSearcher:
    """Web-Suche über SerpApi. Liefert [{title, link, snippet}]."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.key = os.environ.get(cfg["search"].get("serpapi_env", "SERPAPI_KEY"), "")

    def search(self, query, n=8):
        if not self.key:
            return []
        try:
            import requests
            r = requests.get("https://serpapi.com/search", params={
                "engine": "google", "q": query, "num": n, "api_key": self.key},
                timeout=self.cfg["harvest"]["request_timeout"])
            r.raise_for_status()
            return [{"title": o.get("title"), "link": o.get("link"), "snippet": o.get("snippet")}
                    for o in r.json().get("organic_results", []) if o.get("link")]
        except Exception:
            return []


# ---------------------------------------------------------------- Extraction
def _domain(url):
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


_JUNK_DOMAINS = ("wikipedia.", "linkedin.", "youtube.", "facebook.", "amazon.",
                 "ebay.", "mascus.", "machinerytrader.", "researchgate.", "alibaba.")


def extract_candidate(result):
    """Suchtreffer -> {name, domain, url} oder None (Aggregatoren/Junk raus)."""
    url = result.get("link") or ""
    dom = _domain(url)
    if not dom or any(j in dom for j in _JUNK_DOMAINS):
        return None
    title = (result.get("title") or "").split(" - ")[0].split(" | ")[0].strip()
    name = title or dom.split(".")[0]
    return {"name": name[:200], "domain": f"https://{dom}", "url": url}


# ---------------------------------------------------------------- Gate
class VLMGate:
    """VLM-Scope-Gate auf Titel+Snippet (kein Bild): in-scope Pattern? ja/nein."""
    def __init__(self, cfg):
        self.cfg = cfg

    def keep(self, name, text, cls, patterns):
        return vlm_filter.keep_candidate(name, text, cls, patterns, self.cfg)


# ---------------------------------------------------------------- Queries
def build_queries(pattern):
    terms = (getattr(pattern, "text_terms", None) or getattr(pattern, "segment", None)
             or getattr(pattern, "name", None) or "")
    terms = str(terms).strip()
    if not terms:
        return []
    # dual-query: geräte-fokussiert + maschinen-fokussiert
    return [f"{terms} manufacturer", f"{terms} tracked machine OEM"]


# ---------------------------------------------------------------- Loop
def discover(session, cfg, patterns, per_pattern=8, searcher=None, gate=None,
             only_patterns=None) -> dict:
    searcher = searcher if searcher is not None else SerpapiSearcher(cfg)
    gate = gate if gate is not None else VLMGate(cfg)
    stats = {"searched": 0, "candidates": 0, "known_skipped": 0,
             "gate_rejected": 0, "gate_inactive": 0, "new": 0, "by_pattern": {}}
    for code, pat in patterns.items():
        if only_patterns and code not in only_patterns:
            continue
        seen_dom = set()
        p_new = 0
        for q in build_queries(pat):
            stats["searched"] += 1
            for res in searcher.search(q, n=per_pattern):
                cand = extract_candidate(res)
                if not cand or cand["domain"] in seen_dom:
                    continue
                seen_dom.add(cand["domain"])
                stats["candidates"] += 1
                # Dedup gegen bestehende DB
                match, tier, _reason, _score = classify(session, cand["name"],
                                                         country=None)
                if match and tier in ("strong", "norm", "substring", "brand"):
                    stats["known_skipped"] += 1
                    continue
                # VLM-Scope-Gate
                text = f"{res.get('title','')} — {res.get('snippet','')}"
                keep, why = gate.keep(cand["name"], text, code, patterns)
                if why == "kein-key":
                    stats["gate_inactive"] += 1
                if not keep:
                    stats["gate_rejected"] += 1
                    continue
                # Überlebender -> als candidate-Org schreiben
                org, _ = upsert_org(session, cand["name"], domain=cand["domain"],
                                    status="candidate")
                session.add(Claim(subject_type="organization", subject_id=org.id,
                                  predicate="discovered_pattern", object_value=code,
                                  source_url=cand["url"], source_type="discovery",
                                  method="discover", confidence=0.4))
                stats["new"] += 1
                p_new += 1
        stats["by_pattern"][code] = p_new
    session.commit()
    stats.update(quality_gate_discovery(stats))
    return stats


def quality_gate_discovery(stats) -> dict:
    """Deine Regel: Yield = neu/(neu+skip); A+B = gate-pass/kandidaten. Warnung bei Sättigung."""
    new, skip = stats["new"], stats["known_skipped"]
    yield_ = new / max(1, new + skip)
    cand = stats["candidates"]
    ab = (cand - stats["gate_rejected"]) / max(1, cand)
    warn = []
    if stats.get("gate_inactive"):
        warn.append("VLM-Gate inaktiv (kein ANTHROPIC_API_KEY) -> Kontamination erwartbar")
    if yield_ < 0.30:
        warn.append(f"Yield {yield_:.0%} < 30%")
    if ab < 0.40:
        warn.append(f"A+B {ab:.0%} < 40%")
    return {"yield": round(yield_, 2), "ab_share": round(ab, 2),
            "quality_warning": "; ".join(warn) or None}
