"""USPTO PatentsView — Patente + Zuordnung (Tech-Signal, Application-Discovery).
Braucht API-Key (env PATENTSVIEW_KEY).
"""
from __future__ import annotations
import os, json, requests
from .base import Connector, ClaimDict

API = "https://search.patentsview.org/api/v1/patent/"


class PatentsViewConnector(Connector):
    name = "patentsview"; source_type = "patentsview"; is_primary = False; needs_key = True

    def __init__(self, key_env="PATENTSVIEW_KEY"):
        self.key = os.environ.get(key_env, "")

    def fetch(self, *, name, country=None, **kw):
        if not self.key:
            return []
        q = {"q": {"assignees.assignee_organization": name},
             "f": ["patent_id", "patent_title"], "o": {"size": 5}}
        try:
            r = requests.get(API, params={"q": json.dumps(q["q"]), "f": json.dumps(q["f"])},
                             headers={"X-Api-Key": self.key}, timeout=25)
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload):
        pats = (payload or {}).get("patents") or []
        if not pats:
            return []
        n = len(pats)
        titles = "; ".join(p.get("patent_title", "")[:60] for p in pats[:3])
        return [ClaimDict("patent_count", str(n), None, "patentsview", 0.7),
                ClaimDict("patent_titles", titles, None, "patentsview", 0.6)]
