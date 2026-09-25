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
from . import source_trust as _trust

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
                 "istockphoto.", "gettyimages.", "dreamstime.", "123rf.", "mascus.",
                 # Bild-CDNs / Thumbnails: dahinter steckt keine lesbare Produktseite
                 "ytimg.", "ggpht.", "pinimg.", "fbcdn.", "twimg.", "i.redd.",
                 "wp.com", "staticflickr.", "cloudfront.", "blogspot.")


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
                                "source": it.get("source", ""), "title": it.get("title", "")})
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
    # Eine Wahrheit: der zentrale Trust-Filter entscheidet (Social/Stock, Marktplatz/
    # Aggregator inkl. TikTok/Alibaba/made-in-china, Thumbnail-CDNs, domainlos).
    return _trust.is_low_trust(url)


# --------------------------------------------------------------- Airtable
class AirtableWriter:
    """Schreibt Kandidaten in die Review-Base. Feldnamen statt IDs (REST akzeptiert das)."""
    def __init__(self, token=None, base=None, table=None, cfg=None):
        self.token = token or os.environ.get("AIRTABLE_TOKEN", "")
        self.base = base or os.environ.get("AIRTABLE_BASE", AIRTABLE_BASE_DEFAULT)
        self.table = table or os.environ.get("AIRTABLE_TABLE", AIRTABLE_TABLE_DEFAULT)
        self.enabled = bool(self.token)
        # Robustheit: transiente Netz-/DNS-Fehler abfangen statt still 0 zu schreiben.
        self.max_retries = 3            # zusaetzliche Versuche nach dem ersten
        self.retry_backoff = 0.5        # Sekunden, verdoppelt sich je Versuch
        self.write_failures = 0         # Records, die trotz Retry NICHT geschrieben wurden
        self.read_failed = False        # True, wenn ein Lese-Aufruf endgueltig scheiterte
        self.last_error = ""            # letzte Fehlermeldung (fuer laute Meldung/Stats)
        import time as _t
        self._sleep = _t.sleep          # injizierbar in Tests (kein echtes Warten)

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    # Transiente Fehler (DNS/Connection/Timeout/429/5xx) werden geretryt; 4xx wie 422
    # (falscher Feldname) NICHT — das ist ein echter Datenfehler und soll sofort sichtbar sein.
    _RETRY_STATUS = (429, 500, 502, 503, 504)

    def _request_with_retry(self, method, url, **kwargs):
        import requests
        attempts = self.max_retries + 1
        resp = None
        for i in range(attempts):
            try:
                resp = requests.request(method, url, **kwargs)
                if resp.status_code in self._RETRY_STATUS and i < attempts - 1:
                    self.last_error = f"HTTP {resp.status_code}"
                    self._sleep(self.retry_backoff * (2 ** i))
                    continue
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:150]}"
                if i < attempts - 1:
                    self._sleep(self.retry_backoff * (2 ** i))
                    continue
                raise
        return resp

    def _patch_batches(self, updates):
        """PATCH in 10er-Batches mit Retry. Zaehlt nicht behebbare Fehler in
        self.write_failures und meldet am Ende LAUT — statt still 0 zurueckzugeben."""
        self.write_failures = 0
        done = 0
        for i in range(0, len(updates), 10):
            batch = updates[i:i + 10]
            try:
                resp = self._request_with_retry(
                    "PATCH", f"https://api.airtable.com/v0/{self.base}/{self.table}",
                    headers=self._hdr(), json={"records": batch, "typecast": True}, timeout=30)
                resp.raise_for_status()
                done += len(resp.json().get("records", []))
            except Exception as e:
                self.write_failures += len(batch)
                body = getattr(getattr(e, "response", None), "text", "")
                self.last_error = f"{type(e).__name__}: {str(e)[:120]} {body[:200]}".strip()
                print(f"  Airtable-Update-Fehler: {e} {body[:200]}")
        if self.write_failures:
            print(f"  ⚠ AIRTABLE: {self.write_failures} Records trotz Retry NICHT geschrieben "
                  f"({self.last_error}). Daten sind in der CSV, aber NICHT in der Base — "
                  f"Netz/DNS oder Feldname pruefen.")
        return done

    def existing_urls(self):
        if not self.enabled:
            return set()
        urls, offset = set(), None
        try:
            for _ in range(20):  # bis 20 Seiten (2000 Records)
                params = {"fields[]": "Bild-URL", "pageSize": 100}
                if offset:
                    params["offset"] = offset
                r = self._request_with_retry(
                    "GET", f"https://api.airtable.com/v0/{self.base}/{self.table}",
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
        except Exception as e:
            self.read_failed = True
            self.last_error = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"  ⚠ Airtable-Lesefehler (existing_urls): {e} — Dedup unvollstaendig.")
        return urls

    def _all_records(self):
        recs, offset = [], None
        try:
            for _ in range(30):
                params = {"pageSize": 100}
                if offset:
                    params["offset"] = offset
                r = self._request_with_retry(
                    "GET", f"https://api.airtable.com/v0/{self.base}/{self.table}",
                    headers=self._hdr(), params=params, timeout=30)
                r.raise_for_status()
                d = r.json()
                recs.extend(d.get("records", []))
                offset = d.get("offset")
                if not offset:
                    break
        except Exception as e:
            self.read_failed = True
            self.last_error = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"  ⚠ Airtable-Lesefehler (_all_records): {e} — Kandidatenliste unvollstaendig!")
        return recs

    def candidates_missing(self, field="HMI-Typ", limit=None):
        """Alle Records, bei denen `field` leer ist -> Kandidaten fuer die Anreicherung.
        Damit werden auch Bilder aus FRUEHEREN Harvest-Laeufen nachgezogen (das lokale
        Manifest enthaelt immer nur den letzten Lauf)."""
        if not self.enabled:
            return []
        out = []
        for rec in self._all_records():
            f = rec.get("fields", {})
            if str(f.get(field, "") or "").strip():
                continue                       # schon angereichert
            url = f.get("Bild-URL")
            if not url:
                continue
            page = f.get("Quell-Seite") or ""
            if not page:                       # Altbestand ohne Quell-Seite: Domain-Wurzel
                from urllib.parse import urlparse
                p = urlparse(url)
                page = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else url
            _pv = str(f.get("Pattern-Vorschlag", "") or "").split()
            pat = _pv[0] if _pv else ""
            titel = str(f.get("Notizen", "") or "").replace("Bildtitel:", "").strip()
            out.append({"url": url, "page": page, "pattern": pat,
                        "title": titel, "query": str(f.get("Query", "") or "")})
            if limit and len(out) >= limit:
                break
        return out

    def candidates_reenrich(self, urteil="Unsicher", limit=None):
        """Records, die die Anreicherung als `urteil` (Default 'Unsicher') markiert hat ->
        nochmal durch die Anreicherung schicken. So bekommen bereits geladene, aber unaufgeloeste
        Quellen (z.B. Seppi, Energreen, FAE) mit funktionierendem Fetch/Resolver doch noch OEM/CAN.
        Anders als candidates_missing werden hier auch Records MIT gesetztem HMI-Typ nachgezogen."""
        if not self.enabled:
            return []
        out = []
        for rec in self._all_records():
            f = rec.get("fields", {})
            if str(f.get("Claude-Urteil", "") or "").strip() != urteil:
                continue
            url = f.get("Bild-URL")
            if not url:
                continue
            page = f.get("Quell-Seite") or ""
            if not page:
                from urllib.parse import urlparse
                p = urlparse(url)
                page = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else url
            _pv = str(f.get("Pattern-Vorschlag", "") or "").split()
            pat = _pv[0] if _pv else ""
            titel = str(f.get("Notizen", "") or "").replace("Bildtitel:", "").strip()
            out.append({"url": url, "page": page, "pattern": pat,
                        "title": titel, "query": str(f.get("Query", "") or "")})
            if limit and len(out) >= limit:
                break
        return out

    def candidates_all(self, limit=None):
        """ALLE Records mit Bild-URL -> komplette Neu-Anreicherung mit der aktuellen Pipeline
        (Aggregator-Aufloesung, Gewicht/Leistung, frisches CAN-Urteil), unabhaengig davon,
        ob sie schon angereichert sind. Fuer den vollen Re-Run ueber den gesamten Bestand."""
        if not self.enabled:
            return []
        out = []
        for rec in self._all_records():
            f = rec.get("fields", {})
            url = f.get("Bild-URL")
            if not url:
                continue
            page = f.get("Quell-Seite") or ""
            if not page:
                from urllib.parse import urlparse
                p = urlparse(url)
                page = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else url
            _pv = str(f.get("Pattern-Vorschlag", "") or "").split()
            pat = _pv[0] if _pv else ""
            titel = str(f.get("Notizen", "") or "").replace("Bildtitel:", "").strip()
            out.append({"url": url, "page": page, "pattern": pat,
                        "title": titel, "query": str(f.get("Query", "") or "")})
            if limit and len(out) >= limit:
                break
        return out

    def update_fields(self, rows, field_map, key="bild_url"):
        """Schreibt beliebige Felder in bestehende Records.
        field_map: {Airtable-Spalte: Schluessel-in-row}. Match ueber Bild-URL."""
        if not self.enabled:
            return 0
        import requests

        def _norm(u):
            return (u or "").split("?")[0].rstrip("/").strip().lower()
        by_url = {}
        for rec in self._all_records():
            u = rec.get("fields", {}).get("Bild-URL")
            if u:
                by_url[_norm(u)] = rec["id"]
        updates, unmatched = [], 0
        for r in rows:
            rid = by_url.get(_norm(r.get(key)))
            if not rid:
                unmatched += 1
                continue
            updates.append({"id": rid,
                            "fields": {col: (r.get(src) if r.get(src) is not None else "")
                                       for col, src in field_map.items()}})
        # Airtable erlaubt einen Record nur EINMAL pro Request -> pro id zusammenfassen
        by_id = {}
        for u in updates:
            by_id[u["id"]] = u
        updates = list(by_id.values())
        print(f"  Airtable: {len(updates)} Records zugeordnet, {unmatched} ohne Treffer "
              f"(von {len(by_url)} Records in der Base).")
        done = self._patch_batches(updates)
        return done

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
                "Anwendungsart": r.get("anwendung", ""), "HMI-Typ": r.get("hmi_typ", "unklar"),
                "CAN-Bus": r.get("can_bus", "unklar"),
                "Preis-EUR": ("" if r.get("preis_eur") in (None, "") else str(r.get("preis_eur"))),
                "Priorität": r.get("prioritaet", ""),
                "Claude-Urteil": r.get("claude_urteil", ""),
                "Claude-Konfidenz": r.get("claude_konfidenz"),
                "Claude-Begründung": r.get("claude_begruendung", "")}})
        by_id = {}
        for u in updates:
            by_id[u["id"]] = u
        updates = list(by_id.values())
        print(f"  Airtable: {len(updates)} Records zugeordnet, {unmatched} ohne Treffer "
              f"(von {len(by_url)} Records in der Base).")
        done = self._patch_batches(updates)
        return done

    def write(self, records):
        """records: Liste von dicts mit fertigen Feldwerten. 10 je Request."""
        if not self.enabled:
            return 0
        self.write_failures = 0
        written = 0
        for i in range(0, len(records), 10):
            batch = [{"fields": r} for r in records[i:i + 10]]
            try:
                r = self._request_with_retry(
                    "POST", f"https://api.airtable.com/v0/{self.base}/{self.table}",
                    headers=self._hdr(), json={"records": batch, "typecast": True}, timeout=30)
                r.raise_for_status()
                written += len(r.json().get("records", []))
                self._sleep(0.25)  # Airtable Rate-Limit 5 req/s schonen
            except Exception as e:
                self.write_failures += len(batch)
                body = getattr(getattr(e, "response", None), "text", "")
                self.last_error = f"{type(e).__name__}: {str(e)[:120]} {body[:200]}".strip()
                print(f"  Airtable-Schreibfehler: {e} {body[:200]}")
        if self.write_failures:
            print(f"  ⚠ AIRTABLE: {self.write_failures} Records trotz Retry NICHT angelegt "
                  f"({self.last_error}). Netz/DNS oder Feldname pruefen.")
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
        "Quell-Seite": cand.get("page", ""),
        "Notizen": ("Bildtitel: " + cand.get("title", "")) if cand.get("title") else "",
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
            manifest_path="agent6_image_candidates.json", only_patterns=None,
            repo=None) -> dict:
    searcher = searcher if searcher is not None else SerpImageSearcher(cfg)
    writer = writer if writer is not None else AirtableWriter(cfg=cfg)
    from .query_repo import queries_for_pattern
    repo_queries = repo.load(typ="Bild", patterns=only_patterns) if repo else {}
    if repo_queries:
        print(f"  Query-Repo: {sum(len(v) for v in repo_queries.values())} aktive Bild-Queries")
        if only_patterns is None:
            # Kein --patterns angegeben -> das Repo bestimmt, welche Patterns laufen.
            # So kommt ein in Airtable aktiviertes Pattern automatisch beim naechsten Lauf dran.
            only_patterns = sorted(repo_queries.keys())
            print(f"  (kein --patterns -> alle aktiven Repo-Patterns: {', '.join(only_patterns)})")
    q_stats = {}
    known = writer.existing_urls() if hasattr(writer, "existing_urls") else set()
    seen = set(known)
    all_records, manifest = [], []
    stats = {"searched": 0, "found": 0, "junk": 0, "dup": 0, "new": 0,
             "by_pattern": {}, "airtable_written": 0,
             "blocked": {"social/stock": 0, "marktplatz": 0, "cdn/thumbnail": 0, "keine-domain": 0}}

    for code, pat in patterns.items():
        if only_patterns and code not in only_patterns:
            continue
        if getattr(pat, "method", "Beides") == "Text":
            stats["by_pattern"][code] = "übersprungen (Text-Pattern)"
            continue
        p_new = 0
        for entry in queries_for_pattern(repo_queries, code, pat, "Bild"):
            q, neg, rid = entry["query"], entry.get("negativ", ""), entry.get("record_id")
            if neg:
                q = q + " " + " ".join("-" + t for t in neg.split())
            q_found = q_new = 0
            stats["searched"] += 1
            for res in searcher.search(q, n=per_pattern):
                url = res.get("url")
                if not url:
                    continue
                stats["found"] += 1; q_found += 1
                if _trust.is_low_trust(url):
                    stats["junk"] += 1
                    reason = _trust.block_reason(url)
                    stats["blocked"][reason] = stats["blocked"].get(reason, 0) + 1
                    continue
                if url in seen:
                    stats["dup"] += 1
                    continue
                seen.add(url)
                cand = {"url": url, "page": res.get("page", ""), "source": res.get("source", ""),
                        "title": res.get("title", ""),
                        "query": q, "id": f"{code}__{_domain(url)}__{len(seen)}"}
                all_records.append(build_record(cand, code))
                manifest.append({"url": url, "pattern": code, "query": q,
                                 "source": cand["source"], "page": res.get("page", "")})
                stats["new"] += 1
                p_new += 1; q_new += 1
            if rid:
                q_stats[rid] = (q_new, q_found)
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
    if repo and q_stats:
        stats["queries_bewertet"] = repo.report(q_stats)
    # Mittlerer Quellen-Score der BEHALTENEN Records (1=cheap, 2=Fachquelle, 3=OEM-direkt).
    kept = [_trust.source_score(r["Bild-URL"]) for r in all_records]
    stats["quellen_score"] = round(sum(kept) / len(kept), 2) if kept else None
    stats.update(quality_gate(stats))
    return stats


def quality_gate(stats) -> dict:
    """Quality-Gate (Trust-Fokus): Yield = neu/gefunden, Cheap-Anteil = geblockt/gefunden,
    Quellen-Score der behaltenen Records. Warnungen nach Pierres Schwellen."""
    found = stats["found"]
    yield_ = stats["new"] / max(1, found)
    cheap_share = stats.get("junk", 0) / max(1, found)
    score = stats.get("quellen_score")
    warn = []
    if found and yield_ < 0.30:
        warn.append(f"Yield {yield_:.0%} < 30% (viel Junk/Duplikate) — Queries schärfen")
    if found and cheap_share >= 0.70:
        warn.append(f"Cheap-Anteil {cheap_share:.0%} ≥ 70% — Queries ziehen fast nur "
                    f"Aggregatoren/Social; Modellnamen statt Gattungsbegriffe nötig")
    if score is not None and score < 2.0:
        warn.append(f"Quellen-Score {score} < 2,0 — zu wenig OEM/Fachquellen")
    return {"yield": round(yield_, 2), "cheap_share": round(cheap_share, 2),
            "quality_warning": "; ".join(warn) or None}


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
    res = harvest(cfg, patterns, per_pattern=args.per_pattern, only_patterns=only,
                  manifest_path=args.out, repo=repo)
    print("BILD-HARVEST:", res)
    if res.get("quality_warning"):
        print("  ⚠ QUALITÄT:", res["quality_warning"])
    if not res.get("airtable_written"):
        print("  (AIRTABLE_TOKEN nicht gesetzt -> nur Manifest geschrieben:", res.get("manifest"), ")")


if __name__ == "__main__":
    main()
