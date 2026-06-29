"""VIES — EU-VAT-Validierung (gratis, ohne Key).

Input: country + vat. Bestätigt Existenz + liefert offiziellen Namen/Adresse.
Reiner Verifikations-Konnektor (kein Discovery). parse() ist netzwerkfrei.
"""
from __future__ import annotations
import requests
from .base import Connector, ClaimDict

API = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{num}"


class VIESConnector(Connector):
    name = "vies"
    source_type = "vies"
    is_primary = True
    needs_key = False

    def fetch(self, *, name=None, country=None, vat=None, **kw) -> list[ClaimDict]:
        if not (country and vat):
            return []
        num = "".join(ch for ch in str(vat) if ch.isalnum())
        if num[:2].isalpha():
            num = num[2:]
        try:
            r = requests.get(API.format(cc=country, num=num), timeout=20,
                             headers={"Accept": "application/json"})
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload) -> list[ClaimDict]:
        d = payload or {}
        if not d.get("isValid"):
            return [ClaimDict("vat_valid", "false", source_type="vies", confidence=0.9)]
        out = [ClaimDict("vat_valid", "true", source_type="vies", confidence=0.95)]
        if d.get("name"):
            out.append(ClaimDict("legal_name", d["name"], source_type="vies", confidence=0.9))
        if d.get("address"):
            out.append(ClaimDict("address", " ".join(str(d["address"]).split()),
                                  source_type="vies", confidence=0.85))
        return out
