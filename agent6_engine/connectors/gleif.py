"""GLEIF-Konnektor — LEI, gratis, ohne Key. Mit Fuzzy-Matching.

Ablauf: (1) exakte Namenssuche wie bisher. (2) Bei Fehltreffer die GLEIF-
Fuzzy-Completion-API, dann den besten Kandidaten STRENG absichern:
Namensähnlichkeit >= fuzzy_min UND (falls Land bekannt) Land muss übereinstimmen.
So wird kein falscher LEI angehängt (der würde beim Re-Resolve falsch mergen).
Fuzzy-Treffer bekommen niedrigere Confidence (0.82) als exakte (0.95).
`parse()`/`_parse_record()` sind netzwerkfrei (offline testbar).
"""
from __future__ import annotations
import re
import requests
from .base import Connector, ClaimDict

API = "https://api.gleif.org/api/v1/lei-records"
FUZZY = "https://api.gleif.org/api/v1/fuzzycompletions"

_SUFFIX = re.compile(
    r"\b(gmbh|ag|se|kg|kgaa|ohg|mbh|ug|co|ltd|limited|inc|incorporated|llc|"
    r"corp|corporation|plc|srl|spa|bv|nv|oy|ab|as|sa|sas|holding|group|company)\b\.?",
    re.I)


def _norm(s):
    s = re.sub(r"\(.*?\)", " ", str(s or ""))          # (AT), (US) ... raus
    s = s.replace("&", " ").lower()
    s = _SUFFIX.sub(" ", s)
    s = re.sub(r"[^a-z0-9äöüß ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    return {t for t in _norm(s).split() if len(t) >= 3}


def _sim(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class GLEIFConnector(Connector):
    name = "gleif"
    source_type = "gleif"
    is_primary = True
    needs_key = False

    def __init__(self, timeout: int = 20, fuzzy: bool = True, fuzzy_min: float = 0.6):
        self.timeout = timeout
        self.fuzzy = fuzzy
        self.fuzzy_min = fuzzy_min

    def _hdr(self):
        return {"Accept": "application/vnd.api+json"}

    def fetch(self, *, name: str, country: str | None = None, **kw):
        # 1) exakte Suche
        try:
            r = requests.get(API, params={"filter[entity.legalName]": name, "page[size]": 1},
                             timeout=self.timeout, headers=self._hdr())
            r.raise_for_status()
            claims = self.parse(r.json())
            if claims:
                return claims
        except Exception:
            pass
        # 2) Fuzzy-Fallback
        if self.fuzzy:
            try:
                fr = requests.get(FUZZY, params={"field": "entity.legalName", "q": name},
                                  timeout=self.timeout, headers=self._hdr())
                fr.raise_for_status()
                lei = self._best_fuzzy(name, fr.json())
                if lei:
                    rr = requests.get(f"{API}/{lei}", timeout=self.timeout, headers=self._hdr())
                    rr.raise_for_status()
                    return self._parse_record(rr.json().get("data"), query_name=name,
                                              country=country, fuzzy=True)
            except Exception:
                pass
        return []

    def _best_fuzzy(self, name, payload):
        best = (None, 0.0)
        for c in (payload or {}).get("data", []):
            val = (c.get("attributes") or {}).get("value")
            lei = ((((c.get("relationships") or {}).get("lei-records") or {}).get("data")) or {}).get("id")
            if not (val and lei):
                continue
            s = _sim(name, val)
            if s > best[1]:
                best = (lei, s)
        return best[0] if best[1] >= self.fuzzy_min else None

    def parse(self, payload):
        data = (payload or {}).get("data") or []
        if not data:
            return []
        rec = data[0] if isinstance(data, list) else data
        return self._parse_record(rec)

    def _parse_record(self, rec, query_name=None, country=None, fuzzy=False):
        if not rec:
            return []
        attr = rec.get("attributes", {})
        ent = attr.get("entity", {})
        lei = attr.get("lei") or rec.get("id")
        legal = (ent.get("legalName") or {}).get("name")
        addr = ent.get("legalAddress", {}) or {}
        rec_country = addr.get("country")
        # Fuzzy-Sicherung
        if fuzzy:
            if country and rec_country and country != rec_country:
                return []
            if query_name and legal and _sim(query_name, legal) < self.fuzzy_min:
                return []
        conf = 0.82 if fuzzy else 0.95
        method = "fuzzy" if fuzzy else "exact"
        addr_str = ", ".join(x for x in [
            " ".join(addr.get("addressLines", []) or []),
            addr.get("postalCode"), addr.get("city"), rec_country] if x)
        url = f"https://search.gleif.org/#/record/{lei}" if lei else None
        out = [ClaimDict("lei", lei, url, "gleif", conf, extra={"match": method})]
        if legal:
            out.append(ClaimDict("legal_name", legal, url, "gleif", conf))
        if addr_str:
            out.append(ClaimDict("address", addr_str, url, "gleif", conf - 0.05))
        if ent.get("status"):
            out.append(ClaimDict("registration_status", ent.get("status"), url, "gleif", conf - 0.05))
        return out
