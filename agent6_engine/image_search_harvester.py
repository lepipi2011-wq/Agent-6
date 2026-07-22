"""Objekt-zentrierter Bild-Harvester — sucht die MASCHINE, nicht die Firma.

Statt OEM-Websites zu ernten, sucht dieser Harvester direkt nach Bildern der
kettengetriebenen Maschinen — über SerpAPI Images mit den Bildsuch-Strings aus
deiner Pattern-DB (Spalte 'Bildsuch-String'). Jeder Treffer landet als Kandidat
mit Pattern-Vorschlag und Bild-Vorschau in der Airtable-Review-Base, wo dein Team
ihn klassifiziert. Ergebnis: höheres Yield, weniger Rad-Rauschen.

ADDITIV: lässt image_harvest.py (OEM-zentriert) unangetastet. Beide Wege speisen
dieselben Patterns und dasselbe Review.

Braucht:  SERPAPI_KEY  (Bildsuche)  und  AIRTABLE_TOKEN  (Schreiben in die Base).
Ohne AIRTABLE_TOKEN wird nur ein lokales Manifest (JSON) geschrieben.
Suche/Schreiben laufen auf deiner Maschine; die Logik ist per Injection offline testbar.
"""
from __future__ import annotations
import os, json, time, datetime
from urllib.parse import urlparse

# Pattern-Code -> exakter Choice-Name in der Airtable-Base "Agent 6 — Bild-Review"
PATTERN_CHOICE = {
    "P1": "P1 Walk-Behind Deichsel", "P2": "P2 Pendant-Box am Kabel",
    "P3": "P3 Tethered Kabel (Inspection)", "P4": "P4 Joystick-Kabine + Display",
    "P5": "P5 Funk non-SIL (Upgrade)", "P6": "P6 Pedana Stand-On",
    "P7": "P7 Concrete Pump Pendant", "P8": "P8 Stump Grinder RC",
    "P9": "P9 Firefighting/Hazmat Robot", "P10": "P10 Stand-On Mini Loader",
    "P11": "P11 Shotcrete Robot Arm", "P12": "P12 Mini Forwarder IQAN",
    "P13": "P13 Vacuum Excavator Pendant", "P14": "P14 Wood Chipper Deichsel",
    "P15": "P15 RC Mulcher Tool Carrier", "P16": "P16 Ag-Robot Tethered/Autonom",
}
AIRTABLE_BASE_DEFAULT = "app86LDE37W8Mb8Rf"
AIRTABLE_TABLE_DEFAULT = "Review"

_JUNK_DOMAINS = ("wikipedia.", "linkedin.", "pinterest.", "youtube.", "facebook.",
                 "instagram.", "amazon.", "ebay.", "alamy.", "shutterstock.",
                 "istockphoto.", "gettyimages.", "dreamstime.", "123rf.", "mascus.")


# --------------------------------------------------------------- Retrieval
class SerpImageSearcher:
    """Google-Bildsuche via SerpAPI -> [{url, page, source}]."""
    def __init__(self, cfg=None, negatives="-wheel -wheeled -truck -forklift"):
        self.key = os.environ.get((cfg or {}).get("search", {}).get("serpapi_env", "SERPAPI_KEY"), "")
        self.timeout = ((cfg or {}).get("harvest", {}) or {}).get("request_timeout", 20)
        self.negatives = negatives

    def search(self, query, n=15):
        if not self.key:
            return []
        try:
            import requests
            q = f"{query} {self.negatives}".strip()
            r = requests.get("https://serpapi.com/search", params={
                "engine": "google_images", "q": q, "num": n, "api_key": self.key},
                timeout=self.timeout)
            r.raise_for_status()
            out = []
            for it in r.json().get("images_results", [])[:n]:
                url = it.get("original") or it.get("thumbnail")
                if url:
                    out.append({"url": url, "page": it.get("link", ""),
                                "source": it.get("source", "")})
            return out
        except Exception:
            return []


def _domain(u):
    try:
        d = urlparse(u).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_junk(url):
    d = _domain(url)
    return (not d) or any(j in d for j in _JUNK_DOMAINS)


# --------------------------------------------------------------- Airtable
class AirtableWriter:
    """Schreibt Kandidaten in die Review-Base. Feldnamen statt IDs (REST akzeptiert das)."""
    def __init__(self, token=None, base=None, table=None, cfg=None):
        self.token = token or os.environ.get("AIRTABLE_TOKEN", "")
        self.base = base or os.environ.get("AIRTABLE_BASE", AIRTABLE_BASE_DEFAULT)
        self.table = table or os.environ.get("AIRTABLE_TABLE", AIRTABLE_TABLE_DEFAULT)
        self.enabled = bool(self.token)

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def existing_urls(self):
        if not self.enabled:
            return set()
        import requests
        urls, offset = set(), None
        try:
            for _ in range(20):  # bis 20 Seiten (2000 Records)
                params = {"fields[]": "Bild-URL", "pageSize": 100}
                if offset:
                    params["offset"] = offset
                r = requests.get(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                 headers=self._hdr(), params=params, timeout=30)
                r.raise_for_status()
                d = r.json()
                for rec in d.get("records", []):
                    u = rec.get("fields", {}).get("Bild-URL")
                    if u:
                        urls.add(u)
                offset = d.get("offset")
                if not offset:
                    break
        except Exception:
            pass
        return urls

    def _all_records(self):
        import requests
        recs, offset = [], None
        try:
            for _ in range(30):
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                r = requests.get(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                 headers=self._hdr(), params=params, timeout=30)
                r.raise_for_status()
                d = r.json()
                recs.extend(d.get("records", []))
                offset = d.get("offset")
                if not offset:
                    break
        except Exception:
            pass
        return recs

    def update_enrichment(self, rows):
        """Schreibt OEM/Modell/Anwendungsart/HMI-Typ in bestehende Records (Match ueber Bild-URL)."""
        if not self.enabled:
            return 0
        import requests

        def _norm(u):
            u = (u or "").split("?")[0].rstrip("/").strip().lower()
            return u
        by_url = {}
        for rec in self._all_records():
            u = rec.get("fields", {}).get("Bild-URL")
            if u:
                by_url[_norm(u)] = rec["id"]
        updates, unmatched = [], 0
        for r in rows:
            rid = by_url.get(_norm(r.get("bild_url")))
            if not rid:
                unmatched += 1
                continue
            updates.append({"id": rid, "fields": {
                "OEM": r.get("oem", ""), "Modell": r.get("modell", ""),
                "Anwendungsart": r.get("anwendung", ""), "HMI-Typ": r.get("hmi_typ", "unklar")}})
        print(f"  Airtable: {len(updates)} Records zugeordnet, {unmatched} ohne Treffer "
              f"(von {len(by_url)} Records in der Base).")
        done = 0
        for i in range(0, len(updates), 10):
            batch = updates[i:i + 10]
            try:
                resp = requests.patch(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                      headers=self._hdr(),
                                      json={"records": batch, "typecast": True}, timeout=30)
                resp.raise_for_status()
                done += len(resp.json().get("records", []))
            except Exception as e:
                body = getattr(getattr(e, "response", None), "text", "")
                print(f"  Airtable-Update-Fehler: {e} {body[:200]}")
        return done

    def write(self, records):
        """records: Liste von dicts mit fertigen Feldwerten. 10 je Request."""
        if not self.enabled:
            return 0
        import requests
        written = 0
        for i in range(0, len(records), 10):
            batch = [{"fields": r} for r in records[i:i + 10]]
            try:
                r = requests.post(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                  headers=self._hdr(),
                                  json={"records": batch, "typecast": True}, timeout=30)
                r.raise_for_status()
                written += len(r.json().get("records", []))
                time.sleep(0.25)  # Airtable Rate-Limit 5 req/s schonen
            except Exception as e:
                print(f"  Airtable-Schreibfehler: {e}")
        return written


def build_record(cand, pattern_code):
    """Kandidat -> Airtable-Feldwerte (Feldnamen)."""
    return {
        "Bild-ID": cand.get("id") or f"{pattern_code}__{_domain(cand['url'])}",
        "Bild": [{"url": cand["url"]}],
        "Bild-URL": cand["url"],
        "Pattern-Vorschlag": PATTERN_CHOICE.get(pattern_code, pattern_code),
        "Query": cand.get("query", ""),
        "Quelle": cand.get("source") or _domain(cand.get("page") or cand["url"]),
        "Status": "Neu",
        "Harvest-Datum": datetime.date.today().isoformat(),
    }


# --------------------------------------------------------------- Queries
def build_queries(pattern):
    """Bildsuch-Strings je Pattern (aus der Pattern-DB)."""
    qs = []
    for attr in ("img_query", "text_terms"):
        v = getattr(pattern, attr, None)
        if v and str(v).strip():
            qs.append(str(v).strip())
    return qs[:2] or ([str(getattr(pattern, "segment", "") or "").strip()] if getattr(pattern, "segment", None) else [])


# --------------------------------------------------------------- Loop
def harvest(cfg, patterns, per_pattern=15, searcher=None, writer=None,
            manifest_path="agent6_image_candidates.json", only_patterns=None) -> dict:
    searcher = searcher if searcher is not None else SerpImageSearcher(cfg)
    writer = writer if writer is not None else AirtableWriter(cfg=cfg)
    known = writer.existing_urls() if hasattr(writer, "existing_urls") else set()
    seen = set(known)
    all_records, manifest = [], []
    stats = {"searched": 0, "found": 0, "junk": 0, "dup": 0, "new": 0,
             "by_pattern": {}, "airtable_written": 0}

    for code, pat in patterns.items():
        if only_patterns and code not in only_patterns:
            continue
        if getattr(pat, "method", "Beides") == "Text":
            stats["by_pattern"][code] = "übersprungen (Text-Pattern)"
            continue
        neg = getattr(pat, "exclude", "")
        p_new = 0
        for q in build_queries(pat):
            if neg:
                q = q + " " + " ".join("-" + t for t in neg.split())
            stats["searched"] += 1
            for res in searcher.search(q, n=per_pattern):
                url = res.get("url")
                if not url:
                    continue
                stats["found"] += 1
                if is_junk(url):
                    stats["junk"] += 1
                    continue
                if url in seen:
                    stats["dup"] += 1
                    continue
                seen.add(url)
                cand = {"url": url, "page": res.get("page", ""), "source": res.get("source", ""),
                        "query": q, "id": f"{code}__{_domain(url)}__{len(seen)}"}
                all_records.append(build_record(cand, code))
                manifest.append({"url": url, "pattern": code, "query": q,
                                 "source": cand["source"], "page": res.get("page", "")})
                stats["new"] += 1
                p_new += 1
        stats["by_pattern"][code] = p_new

    # lokales Manifest immer schreiben (Backup / fürs Review-Widget)
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        stats["manifest"] = manifest_path
    except Exception:
        pass
    # Airtable, falls verbunden
    if getattr(writer, "enabled", False) and all_records:
        stats["airtable_written"] = writer.write(all_records)
    stats.update(quality_gate(stats))
    return stats


def quality_gate(stats) -> dict:
    """Deine Regel: Yield = neu/gefunden; Warnung bei viel Junk/Duplikaten."""
    found = stats["found"]
    yield_ = stats["new"] / max(1, found)
    warn = []
    if found and yield_ < 0.30:
        warn.append(f"Yield {yield_:.0%} < 30% (viel Junk/Duplikate) — Queries schärfen")
    return {"yield": round(yield_, 2), "quality_warning": "; ".join(warn) or None}


def main():
    import argparse
    from .config import load_config
    from . import master_io as M
    ap = argparse.ArgumentParser(description="Objekt-zentrierter Bild-Harvester -> Airtable")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--patterns", default=None, help="nur diese Codes, z.B. P4,P5")
    ap.add_argument("--per-pattern", dest="per_pattern", type=int, default=15)
    ap.add_argument("--patterns-file", dest="patterns_file", default=None,
                    help="patterns.json statt Master (für Automatik)")
    ap.add_argument("--out", default="agent6_image_candidates.json")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.patterns_file:
        patterns = M.load_patterns_json(args.patterns_file)
    else:
        patterns = M.read_patterns(M.open_master(cfg), cfg)
    only = [p.strip() for p in args.patterns.split(",")] if args.patterns else None
    res = harvest(cfg, patterns, per_pattern=args.per_pattern, only_patterns=only,
                  manifest_path=args.out)
    print("BILD-HARVEST:", res)
    if res.get("quality_warning"):
        print("  ⚠ QUALITÄT:", res["quality_warning"])
    if not res.get("airtable_written"):
        print("  (AIRTABLE_TOKEN nicht gesetzt -> nur Manifest geschrieben:", res.get("manifest"), ")")


if __name__ == "__main__":
    main()
