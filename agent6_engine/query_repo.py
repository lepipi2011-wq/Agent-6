"""Query-Repository — die Suchanfragen leben in Airtable, nicht im Code.

Warum: Suchanfragen nutzen sich ab (dieselbe Query liefert bei Google immer dieselben
Treffer). Damit das System dauerhaft Neues findet, muessen regelmaessig neue Queries
dazukommen — und das soll das TEAM koennen, ohne Code anzufassen.

Die Tabelle "Queries" in der Review-Base ist das zentrale Repository:
  Query | Pattern | Typ (Bild/Text) | Sprache | Aktiv | Negativ-Terme | Angelegt von
  + Rueckmeldung aus den Laeufen: Letzter Lauf | Neue Treffer | Treffer gesamt | Yield

So sieht jeder, welche Query liefert und welche nicht — Grundlage fuer Pflege.
Faellt Airtable aus oder ist kein Token gesetzt, greifen die Harvester auf
patterns.json zurueck (kein Ausfall).
"""
from __future__ import annotations
import os, datetime

TABLE_DEFAULT = "Queries"

# ---------------------------------------------------------------- Scope-Waechter
# Out-of-Scope: was NICHT gesucht werden darf (Anti-Pattern aus der Projekt-Historie)
SCOPE_VERBOTEN = {
    "raeder": ["wheel loader", "wheeled", "radlader", "forklift", "stapler", "truck", "lkw",
               "skid steer wheel", "telehandler", "teleskoplader"],
    "unterwasser_kanal": ["underwater", "subsea", "rov", "unterwasser", "sewer",
                          "kanal", "pipe inspection", "rohr", "drain", "abwasser"],
    "anti_pattern": ["schreitbagger", "walking excavator", "spmt", "agv", "fahrerloses",
                     "tbm", "tunnelbohr", "seilbagger", "dragline"],
    "spielzeug_privat": ["toy", "rc car", "modellbau", "hobby", "spielzeug", "lego", "gaming",
                         "joystick pc", "thrustmaster"],
    "bauteil_statt_maschine": ["cable datasheet", "kabel datenblatt", "connector", "stecker",
                               "chip", "protocol", "protokoll", "wikipedia"],
}
# Mindestens EINER dieser Begriffe muss vorkommen (Scope-Anker: kettengetrieben)
SCOPE_PFLICHT = ["tracked", "crawler", "kette", "ketten", "raupe", "raupen", "cingolat",
                 "chenille", "undercarriage", "band", "walk-behind", "stand-on", "pedana"]


def validate_query(query, negativ="") -> tuple[bool, str]:
    """Prueft eine Query gegen den Scope. -> (ok, begruendung).
    Verhindert, dass Out-of-Scope-Queries ueberhaupt ausgefuehrt werden."""
    q = " ".join(str(query or "").lower().split())
    if not q:
        return False, "leer"
    neg = " ".join(str(negativ or "").lower().split())
    import re as _re
    for gruppe, begriffe in SCOPE_VERBOTEN.items():
        for b in begriffe:
            # Wortgrenzen: "chip" darf "chipper" nicht blocken
            if _re.search(rf"\b{_re.escape(b)}\b", q) and not _re.search(rf"\b{_re.escape(b)}\b", neg):
                return False, f"out-of-scope ({gruppe}): '{b}'"
    if _re.search(r"\btunnel\b", q) and _re.search(r"\b(inspection|inspektion|kamera|camera)\b", q):
        return False, "out-of-scope: Tunnel-Inspektion (Kabel fuehrt Strom, Funk unmoeglich)"
    if not any(a in q for a in SCOPE_PFLICHT):
        return False, ("kein Scope-Anker — Query muss kettengetrieben eingrenzen "
                       "(tracked/crawler/Ketten/Raupe/cingolato/…)")
    return True, "ok"




class QueryRepo:
    """Liest aktive Queries aus Airtable und schreibt Trefferzahlen zurueck."""

    def __init__(self, token=None, base=None, table=None):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass
        from .image_search_harvester import AIRTABLE_BASE_DEFAULT
        self.token = token or os.environ.get("AIRTABLE_TOKEN", "")
        self.base = base or os.environ.get("AIRTABLE_BASE", AIRTABLE_BASE_DEFAULT)
        self.table = table or os.environ.get("AIRTABLE_QUERY_TABLE", TABLE_DEFAULT)
        self.enabled = bool(self.token)
        self._records = []
        self.abgelehnt = []

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _fetch(self):
        if not self.enabled:
            return []
        import requests
        recs, offset = [], None
        try:
            for _ in range(20):
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
        except Exception as e:
            print(f"  Query-Repo nicht lesbar ({e}) — nutze patterns.json")
            return []
        self._records = recs
        return recs

    def load(self, typ=None, patterns=None) -> dict:
        """-> {pattern_code: [ {query, negativ, sprache, record_id}, ... ]}.
        Nur AKTIVE und SCOPE-KONFORME Queries; abgelehnte stehen in self.abgelehnt."""
        out = {}
        self.abgelehnt = []
        for rec in self._fetch():
            f = rec.get("fields", {})
            if not f.get("Aktiv"):
                continue
            q = str(f.get("Query", "") or "").strip()
            if not q:
                continue
            ok, grund = validate_query(q, f.get("Negativ-Terme", ""))
            if not ok:
                self.abgelehnt.append((rec["id"], q, grund))
                continue
            if typ and str(f.get("Typ", "") or "").strip() != typ:
                continue
            code = str(f.get("Pattern", "") or "").strip()
            if patterns and code not in patterns:
                continue
            out.setdefault(code, []).append({
                "query": q,
                "negativ": str(f.get("Negativ-Terme", "") or "").strip(),
                "sprache": str(f.get("Sprache", "") or "").strip(),
                "record_id": rec["id"],
                "treffer_gesamt": f.get("Treffer gesamt") or 0,
            })
        return out


    def existing_queries(self) -> set:
        return {str(r.get("fields", {}).get("Query", "") or "").strip().lower()
                for r in self._fetch()}

    def seed_from_patterns(self, patterns_json="patterns.json", dry=False) -> dict:
        """Traegt die Standard-Queries aus patterns.json ein (nur was fehlt).
        Damit ist das Repository von Anfang an gefuellt, nicht leer."""
        import json, requests
        try:
            pats = json.load(open(patterns_json, encoding="utf-8"))
        except Exception as e:
            return {"fehler": f"patterns.json nicht lesbar: {e}"}
        vorhanden = self.existing_queries() if self.enabled else set()
        neu, abgelehnt = [], []
        for p in pats:
            code = p.get("code", "")
            method = p.get("method", "Beides")
            paare = []
            if method in ("Bild", "Beides") and p.get("img_query"):
                paare.append(("Bild", p["img_query"]))
            if method in ("Text", "Beides"):
                tq = p.get("text_query") or p.get("text_terms")
                if tq:
                    paare.append(("Text", tq))
            for typ, q in paare:
                q = str(q).strip()
                if not q or q.lower() in vorhanden:
                    continue
                ok, grund = validate_query(q, p.get("exclude", ""))
                if not ok:
                    abgelehnt.append((code, typ, q, grund))
                    continue
                neu.append({"fields": {
                    "Query": q, "Pattern": code, "Typ": typ, "Aktiv": True,
                    "Negativ-Terme": p.get("exclude", ""), "Angelegt von": "Standard (patterns.json)",
                    "Notiz": f"Automatisch aus patterns.json — Segment: {p.get('segment','')}"}})
                vorhanden.add(q.lower())
        res = {"neu": len(neu), "abgelehnt": len(abgelehnt), "details_abgelehnt": abgelehnt}
        if dry or not self.enabled:
            res["hinweis"] = "Trockenlauf (nichts geschrieben)"
            return res
        geschrieben = 0
        for i in range(0, len(neu), 10):
            try:
                r = requests.post(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                  headers=self._hdr(),
                                  json={"records": neu[i:i+10], "typecast": True}, timeout=30)
                r.raise_for_status()
                geschrieben += len(r.json().get("records", []))
            except Exception as e:
                body = getattr(getattr(e, "response", None), "text", "")
                print(f"  Seed-Fehler: {e} {body[:200]}")
        res["geschrieben"] = geschrieben
        return res

    def report(self, results) -> int:
        """results: {record_id: (neue_treffer, gefunden)} -> schreibt Performance zurueck."""
        if not self.enabled or not results:
            return 0
        import requests
        prev = {r["id"]: (r.get("fields", {}).get("Treffer gesamt") or 0)
                for r in (self._records or self._fetch())}
        heute = datetime.date.today().isoformat()
        updates = []
        for rid, (neu, gefunden) in results.items():
            y = round(neu / gefunden, 2) if gefunden else 0
            updates.append({"id": rid, "fields": {
                "Letzter Lauf": heute, "Neue Treffer": neu,
                "Treffer gesamt": (prev.get(rid) or 0) + neu, "Yield": y}})
        done = 0
        for i in range(0, len(updates), 10):
            try:
                r = requests.patch(f"https://api.airtable.com/v0/{self.base}/{self.table}",
                                   headers=self._hdr(),
                                   json={"records": updates[i:i + 10], "typecast": True}, timeout=30)
                r.raise_for_status()
                done += len(r.json().get("records", []))
            except Exception as e:
                print(f"  Query-Repo-Update-Fehler: {e}")
        return done


def queries_for_pattern(repo_queries, code, pattern, typ) -> list:
    """Queries aus dem Repo; falls dort nichts steht, Fallback auf patterns.json."""
    entries = (repo_queries or {}).get(code) or []
    if entries:
        return entries
    fb = (getattr(pattern, "img_query", "") if typ == "Bild"
          else getattr(pattern, "text_query", "") or getattr(pattern, "text_terms", ""))
    fb = (fb or "").strip()
    if not fb:
        return []
    return [{"query": fb, "negativ": getattr(pattern, "exclude", "") or "",
             "sprache": "", "record_id": None, "treffer_gesamt": 0}]


def main():
    """Zeigt den Inhalt des Repositories (Uebersicht fuers Team)."""
    import argparse
    ap = argparse.ArgumentParser(description="Query-Repository anzeigen")
    ap.add_argument("--typ", default=None, choices=["Bild", "Text"])
    ap.add_argument("--seed", action="store_true",
                    help="Standard-Queries aus patterns.json eintragen (nur fehlende)")
    ap.add_argument("--patterns-file", dest="patterns_file", default="patterns.json")
    ap.add_argument("--dry", action="store_true", help="nur zeigen, nichts schreiben")
    ap.add_argument("--check", action="store_true",
                    help="alle Eintraege gegen den Scope pruefen und Verstoesse melden")
    args = ap.parse_args()
    repo = QueryRepo()
    if not repo.enabled:
        print("AIRTABLE_TOKEN fehlt.")
        return
    if args.seed:
        res = repo.seed_from_patterns(args.patterns_file, dry=args.dry)
        print("SEED:", {k: v for k, v in res.items() if k != "details_abgelehnt"})
        for code, typ, q, grund in res.get("details_abgelehnt", []):
            print(f"  ⚠ {code}/{typ} abgelehnt: {q[:55]} -> {grund}")
        return
    qs = repo.load(typ=args.typ)
    if args.check or repo.abgelehnt:
        if repo.abgelehnt:
            print(f"⚠ {len(repo.abgelehnt)} Query(s) verletzen den Scope und werden NICHT ausgefuehrt:")
            for rid, q, grund in repo.abgelehnt:
                print(f"   {q[:60]} -> {grund}")
        else:
            print("✓ Alle aktiven Queries sind scope-konform.")
        if args.check:
            return
    if not qs:
        print("Keine aktiven Queries gefunden. Tabelle 'Queries' anlegen und befuellen.")
        return
    total = 0
    for code in sorted(qs, key=lambda c: (len(c), c)):
        print(f"\n{code}:")
        for e in qs[code]:
            total += 1
            print(f"  [{e['sprache'] or '--'}] {e['query'][:70]}"
                  + (f"   (gesamt {e['treffer_gesamt']})" if e["treffer_gesamt"] else ""))
    print(f"\n{total} aktive Queries.")


if __name__ == "__main__":
    main()
