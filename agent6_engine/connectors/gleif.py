"""GLEIF-Konnektor — Legal Entity Identifier (LEI), gratis, ohne API-Key.

Liefert den starken kanonischen Schlüssel (LEI) + offiziellen Rechtsnamen +
Sitz-Adresse + Status. Primärquelle. `parse()` ist netzwerkfrei (offline testbar);
`fetch()` macht den Live-Call (läuft auf der Zielmaschine, nicht in der Sandbox).
"""
from __future__ import annotations
import requests
from .base import Connector, ClaimDict

API = "https://api.gleif.org/api/v1/lei-records"


class GLEIFConnector(Connector):
    name = "gleif"
    source_type = "gleif"
    is_primary = True
    needs_key = False

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def fetch(self, *, name: str, country: str | None = None, **kw) -> list[ClaimDict]:
        params = {"filter[entity.legalName]": name, "page[size]": 1}
        if country:
            params["filter[entity.legalAddress.country]"] = country
        try:
            r = requests.get(API, params=params, timeout=self.timeout,
                             headers={"Accept": "application/vnd.api+json"})
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload) -> list[ClaimDict]:
        data = (payload or {}).get("data") or []
        if not data:
            return []
        rec = data[0]
        attr = rec.get("attributes", {})
        ent = attr.get("entity", {})
        lei = attr.get("lei") or rec.get("id")
        legal_name = (ent.get("legalName") or {}).get("name")
        addr = ent.get("legalAddress", {}) or {}
        addr_str = ", ".join(x for x in [
            " ".join(addr.get("addressLines", []) or []),
            addr.get("postalCode"), addr.get("city"), addr.get("country")] if x)
        status = ent.get("status")
        url = f"https://search.gleif.org/#/record/{lei}" if lei else None
        out = [ClaimDict("lei", lei, url, "gleif", 0.95)]
        if legal_name:
            out.append(ClaimDict("legal_name", legal_name, url, "gleif", 0.95))
        if addr_str:
            out.append(ClaimDict("address", addr_str, url, "gleif", 0.9))
        if status:
            out.append(ClaimDict("registration_status", status, url, "gleif", 0.9))
        return out
