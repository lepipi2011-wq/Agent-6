"""Text-Harvester — findet In-Scope-Kandidaten über die SPRACHE der Datenblätter.

Bild sagt "sieht aus wie Kette", Text sagt "HAT Kettenfahrwerk + CAN + Funk" — für
die Scope-Entscheidung ist Text oft präziser. Dieser Harvester sucht per SerpAPI-Web
nach Spec-Sprache je Pattern (Kettenfahrwerk / tracked undercarriage + CAN-Bus +
Funkfernsteuerung + Referenz-OEM-Wettbewerber) und liefert bewertete Kandidaten
(OEM/Produkt + Quelle + Snippet + Treffer-Terme) als CSV/JSON — direkt für die
SDR-Verifikation und als Saat für die Bildsuche.

ADDITIV: eigener Baustein neben image_search_harvester.py. Braucht SERPAPI_KEY.
Quality-Gate nach deiner Regel: Yield, A+B-Anteil (starke Treffer), Quellen-Score.
"""
from __future__ import annotations
import os, csv, json, datetime
from urllib.parse import urlparse

# Spec-Anker: die Sprache, die ein In-Scope-Datenblatt benutzt
SPEC_ANCHORS = ["Kettenfahrwerk", "tracked undercarriage", "crawler", "CAN-Bus",
                "Funkfernsteuerung", "remote control", "cable pendant", "radio remote"]

_AGGREGATORS = ("mascus.", "machineryzone.", "directindustry.", "europages.",
                "exapro.", "tradertag.", "alibaba.", "made-in-china.", "indiamart.",
                "linkedin.", "facebook.", "youtube.", "wikipedia.")
_PRESS = ("khl.com", "internationalconstruction", "constructionequipment", "forconstruction",
          "worldhighways", "recyclingtoday", "iwr", "press", "news", "magazin")


def _domain(u):
    try:
        d = urlparse(u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def source_score(url) -> int:
    """1 = Aggregator, 2 = Presse, 3 = OEM/Primärquelle (deine Quellen-Score-Regel)."""
    d = _domain(url)
    if not d:
        return 1
    if any(a in d for a in _AGGREGATORS):
        return 1
    if any(p in d for p in _PRESS):
        return 2
    return 3


def matched_terms(text) -> list:
    t = (text or "").lower()
    return [a for a in SPEC_ANCHORS if a.lower() in t]


class SerpTextSearcher:
    """Google-Websuche via SerpAPI -> [{title, url, snippet, source}]."""
    def __init__(self, cfg=None):
        self.key = os.environ.get((cfg or {}).get("search", {}).get("serpapi_env", "SERPAPI_KEY"), "")
        self.timeout = ((cfg or {}).get("harvest", {}) or {}).get("request_timeout", 20)

    def search(self, query, n=10):
        if not self.key:
            return []
        try:
            import requests
            r = requests.get("https://serpapi.com/search", params={
                "engine": "google", "q": query, "num": n, "api_key": self.key},
                timeout=self.timeout)
            r.raise_for_status()
            out = []
            for it in r.json().get("organic_results", [])[:n]:
                link = it.get("link")
                if link:
                    out.append({"title": it.get("title", ""), "url": link,
                                "snippet": it.get("snippet", ""),
                                "source": it.get("source", _domain(link))})
            return out
        except Exception:
            return []


def build_spec_queries(pattern):
    """Bevorzugt den kuratierten text_query (maschinen-zentriert); sonst Fallback."""
    tq = (getattr(pattern, "text_query", "") or "").strip()
    if tq:
        return [tq]
    qs = []
    seg = (getattr(pattern, "segment", "") or "").strip()
    ref = (getattr(pattern, "text_terms", "") or getattr(pattern, "img_query", "") or "").strip()
    ref_oem = (getattr(pattern, "ref_oem", "") or "").strip()
    if seg:
        qs.append(f"{seg} Kettenfahrwerk CAN Funkfernsteuerung Hersteller")
        qs.append(f"{seg} tracked remote control datasheet")
    if ref_oem:
        # ersten Referenz-OEM-Namen als Wettbewerber-Anker
        first = ref_oem.split("/")[0].split()[0:2]
        if first:
            qs.append(f"{' '.join(first)} competitors tracked machine remote control")
    if not qs and ref:
        qs.append(f"{ref} datasheet")
    return qs[:3]


_JUNK = ("wikipedia.", "amazon.", "ebay.", "aliexpress.", "walmart.", "thrustmaster.",
         "twitch.", "instagram.", "pinterest.", "reddit.", "quora.", "twitter.", "x.com",
         "tiktok.", "youtube.", "facebook.", "linkedin.")


def is_junk(url):
    d = _domain(url)
    return (not d) or any(j in d for j in _JUNK) or any(a in d for a in _AGGREGATORS)


def default_judge(cfg, patterns):
    """LLM-Urteilsschicht: liest Titel+Snippet und entscheidet In-Scope — wie ein
    Mensch, der die Treffer liest, statt nur Stichwörter zu zählen.
    Kein ANTHROPIC_API_KEY -> lässt alles durch (Gate inaktiv)."""
    from .vlm_filter import keep_candidate

    def _judge(name, text, code):
        return keep_candidate(name, text, code, patterns, cfg)
    return _judge


def harvest(cfg, patterns, per_query=10, searcher=None, only_patterns=None,
            out_csv="agent6_text_candidates.csv", out_json="agent6_text_candidates.json",
            gate=None, judge=None, use_llm=True, repo=None) -> dict:
    searcher = searcher if searcher is not None else SerpTextSearcher(cfg)
    if judge is None and use_llm:
        judge = default_judge(cfg, patterns)
    from .query_repo import queries_for_pattern
    repo_queries = repo.load(typ="Text", patterns=only_patterns) if repo else {}
    if repo_queries:
        print(f"  Query-Repo: {sum(len(v) for v in repo_queries.values())} aktive Text-Queries")
        if only_patterns is None:
            only_patterns = sorted(repo_queries.keys())
            print(f"  (kein --patterns -> alle aktiven Repo-Patterns: {', '.join(only_patterns)})")
    q_stats = {}
    seen, rows = set(), []
    stats = {"searched": 0, "found": 0, "dup": 0, "judged": 0, "llm_rejected": 0,
             "new": 0, "strong": 0, "score_sum": 0, "by_pattern": {}}

    for code, pat in patterns.items():
        if only_patterns and code not in only_patterns:
            continue
        if getattr(pat, "method", "Beides") == "Bild":
            stats["by_pattern"][code] = "übersprungen (Bild-Pattern)"
            continue
        p_new = 0
        _entries = (repo_queries or {}).get(code) or [
            {"query": q, "negativ": "", "sprache": "", "record_id": None}
            for q in build_spec_queries(pat)]
        for entry in _entries:
            q, rid = entry["query"], entry.get("record_id")
            q_found = q_new = 0
            stats["searched"] += 1
            for res in searcher.search(q, n=per_query):
                url = res.get("url")
                if not url or is_junk(url):
                    continue
                stats["found"] += 1; q_found += 1
                key = _domain(url)
                if key in seen:
                    stats["dup"] += 1
                    continue
                seen.add(key)
                title, snip = res.get("title", ""), res.get("snippet", "")
                name = res.get("source", "") or key
                # LLM-Urteil: liest Titel+Snippet, verwirft Bauteile/Händler/Rad
                llm_reason = ""
                if judge is not None:
                    stats["judged"] += 1
                    keep, llm_reason = judge(name, f"{title} — {snip}", code)
                    if not keep:
                        stats["llm_rejected"] += 1
                        continue
                terms = matched_terms(title + " " + snip)
                sc = source_score(url)
                strong = len(terms) >= 2 and sc >= 2
                rows.append({
                    "pattern": code, "oem_guess": name,
                    "url": url, "title": title,
                    "snippet": (snip or "")[:300],
                    "matched_terms": ", ".join(terms), "n_terms": len(terms),
                    "source_domain": key, "source_score": sc,
                    "strong": "A/B" if strong else "", "llm_urteil": llm_reason,
                    "query": q, "harvested_at": datetime.date.today().isoformat(),
                })
                stats["new"] += 1
                stats["score_sum"] += sc
                if strong:
                    stats["strong"] += 1
                p_new += 1; q_new += 1
            if rid:
                q_stats[rid] = (q_new, q_found)
        stats["by_pattern"][code] = p_new

    _write_csv(rows, out_csv)
    try:
        json.dump(rows, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    if repo and q_stats:
        stats["queries_bewertet"] = repo.report(q_stats)
    stats["out_csv"] = out_csv
    stats.update((gate or quality_gate)(stats))
    return stats


def _write_csv(rows, path):
    cols = ["pattern", "oem_guess", "url", "title", "snippet", "matched_terms",
            "n_terms", "source_domain", "source_score", "strong", "llm_urteil", "query", "harvested_at"]
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except Exception:
        pass


def quality_gate(stats) -> dict:
    """Deine 3 Metriken: Yield, A+B-Anteil, Quellen-Score. 2 von 3 reißen -> Stop-Empfehlung."""
    new = max(1, stats["new"])
    found = max(1, stats["found"])
    yield_ = stats["new"] / found
    ab = stats["strong"] / new
    score = stats["score_sum"] / new
    breaches = []
    if yield_ < 0.30:
        breaches.append(f"Yield {yield_:.0%}<30%")
    if ab < 0.40:
        breaches.append(f"A+B {ab:.0%}<40%")
    if score < 2.0:
        breaches.append(f"Score {score:.1f}<2.0")
    out = {"yield": round(yield_, 2), "ab_share": round(ab, 2), "source_score": round(score, 2)}
    if len(breaches) >= 2:
        out["STOP"] = ("Sättigung: " + ", ".join(breaches) +
                       ". Vorschlag: Queries/Spec-Anker schärfen oder anderes Pattern.")
    return out


def main():
    import argparse
    from .config import load_config
    from . import master_io as M
    ap = argparse.ArgumentParser(description="Text-Harvester: Spec-Sprache je Pattern -> CSV")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--patterns", default=None, help="nur diese Codes, z.B. P4,P5")
    ap.add_argument("--patterns-file", dest="patterns_file", default=None,
                    help="patterns.json statt Master (für Automatik)")
    ap.add_argument("--per-query", dest="per_query", type=int, default=10)
    ap.add_argument("--no-judge", dest="no_judge", action="store_true",
                    help="LLM-Urteilsschicht aus (nur Keyword) — schneller/gratis, aber mehr Rauschen")
    ap.add_argument("--out", default="agent6_text_candidates.csv")
    ap.add_argument("--no-repo", dest="no_repo", action="store_true",
                    help="Query-Repo (Airtable) ignorieren, nur patterns.json nutzen")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.patterns_file:
        patterns = M.load_patterns_json(args.patterns_file)
    else:
        patterns = M.read_patterns(M.open_master(cfg), cfg)
    only = [p.strip() for p in args.patterns.split(",")] if args.patterns else None
    repo = None
    if not args.no_repo:
        from .query_repo import QueryRepo
        r = QueryRepo()
        repo = r if r.enabled else None
    res = harvest(cfg, patterns, per_query=args.per_query, only_patterns=only,
                  out_csv=args.out, use_llm=not args.no_judge, repo=repo)
    print("TEXT-HARVEST:", res)
    if res.get("STOP"):
        print("  ⛔ STOP:", res["STOP"])


if __name__ == "__main__":
    main()
