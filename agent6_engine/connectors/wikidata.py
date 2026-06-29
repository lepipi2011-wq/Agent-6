"""Wikidata — SPARQL (gratis, ohne Key).

Firmographie-Anreicherung: offizielle Website, Land, Hauptsitz, Branche.
Zeigt zugleich, dass 'Suche' quellenabhängig eine echte Abfragesprache sein kann
(SPARQL) statt fixer Befehle. parse() ist netzwerkfrei (Standard-SPARQL-JSON).
"""
from __future__ import annotations
import requests
from .base import Connector, ClaimDict

ENDPOINT = "https://query.wikidata.org/sparql"

_QUERY = """
SELECT ?item ?itemLabel ?website ?countryLabel ?industryLabel WHERE {{
  ?item rdfs:label "{name}"@en .
  OPTIONAL {{ ?item wdt:P856 ?website. }}
  OPTIONAL {{ ?item wdt:P17 ?country. }}
  OPTIONAL {{ ?item wdt:P452 ?industry. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,de". }}
}} LIMIT 1
"""


class WikidataConnector(Connector):
    name = "wikidata"
    source_type = "wikidata"
    is_primary = False
    needs_key = False

    def fetch(self, *, name, country=None, **kw) -> list[ClaimDict]:
        try:
            r = requests.get(ENDPOINT, params={"query": _QUERY.format(name=name), "format": "json"},
                             timeout=25, headers={"User-Agent": "Agent6/1.0"})
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload) -> list[ClaimDict]:
        rows = ((payload or {}).get("results") or {}).get("bindings") or []
        if not rows:
            return []
        b = rows[0]
        def val(k):
            return (b.get(k) or {}).get("value")
        url = val("item")
        out = []
        if val("website"):
            out.append(ClaimDict("domain", val("website"), url, "wikidata", 0.7))
        if val("countryLabel"):
            out.append(ClaimDict("country_name", val("countryLabel"), url, "wikidata", 0.7))
        if val("industryLabel"):
            out.append(ClaimDict("industry", val("industryLabel"), url, "wikidata", 0.7))
        return out
