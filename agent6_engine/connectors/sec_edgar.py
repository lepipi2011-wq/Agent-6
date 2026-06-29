"""SEC EDGAR — US-Börsenfirmen (gratis, kein Key; SEC verlangt User-Agent).
Liefert CIK (starker US-Schlüssel für public companies) + Name. Nur public.
"""
from __future__ import annotations
import re, requests
from .base import Connector, ClaimDict

API = "https://efts.sec.gov/LATEST/search-index"


class SECEdgarConnector(Connector):
    name = "sec_edgar"; source_type = "sec_edgar"; is_primary = True; needs_key = False

    def fetch(self, *, name, country=None, **kw):
        if country and country not in ("US", "USA"):
            return []
        try:
            r = requests.get(API, params={"q": f'"{name}"'}, timeout=20,
                             headers={"User-Agent": "Agent6 research contact@nbb.local"})
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload):
        hits = (((payload or {}).get("hits") or {}).get("hits")) or []
        if not hits:
            return []
        src = hits[0].get("_source", {})
        names = src.get("display_names") or []
        disp = names[0] if names else ""
        m = re.search(r"CIK\s*(\d{4,10})", disp)
        cik = m.group(1) if m else src.get("cik")
        legal = re.sub(r"\s*\(CIK.*\)", "", disp).strip() or None
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}" if cik else None
        out = []
        if cik:
            out.append(ClaimDict("cik", str(cik), url, "sec_edgar", 0.9))
        if legal:
            out.append(ClaimDict("legal_name", legal, url, "sec_edgar", 0.85))
        return out
