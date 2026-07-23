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


class QueryRepo:
    """Liest aktive Queries aus Airtable und schreibt Trefferzahlen zurueck."""

    def __init__(self, token=None, base=None, table=None):
        from .image_search_harvester import AIRTABLE_BASE_DEFAULT
        self.token = token or os.environ.get("AIRTABLE_TOKEN", "")
        self.base = base or os.environ.get("AIRTABLE_BASE", AIRTABLE_BASE_DEFAULT)
        self.table = table or os.environ.get("AIRTABLE_QUERY_TABLE", TABLE_DEFAULT)
        self.enabled = bool(self.token)
        self._records = []

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
        """-> {pattern_code: [ {query, negativ, sprache, record_id}, ... ]} (nur Aktiv)."""
        out = {}
        for rec in self._fetch():
            f = rec.get("fields", {})
            if not f.get("Aktiv"):
                continue
            q = str(f.get("Query", "") or "").strip()
            if not q:
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
    args = ap.parse_args()
    repo = QueryRepo()
    if not repo.enabled:
        print("AIRTABLE_TOKEN fehlt.")
        return
    qs = repo.load(typ=args.typ)
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
