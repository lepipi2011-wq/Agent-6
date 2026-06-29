"""SAM.gov — US-Bundesauftragnehmer, UEI (ersetzt DUNS). Braucht freien API-Key
(env SAM_GOV_KEY). Besonders relevant für Defense/Militär-OEMs.
"""
from __future__ import annotations
import os, requests
from .base import Connector, ClaimDict

API = "https://api.sam.gov/entity-information/v3/entities"


class SAMGovConnector(Connector):
    name = "sam_gov"; source_type = "sam_gov"; is_primary = True; needs_key = True

    def __init__(self, key_env="SAM_GOV_KEY"):
        self.key = os.environ.get(key_env, "")

    def fetch(self, *, name, country=None, **kw):
        if not self.key or (country and country not in ("US", "USA")):
            return []
        try:
            r = requests.get(API, params={"api_key": self.key, "legalBusinessName": name,
                             "includeSections": "entityRegistration,coreData"}, timeout=25)
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload):
        data = (payload or {}).get("entityData") or []
        if not data:
            return []
        e = data[0]
        reg = e.get("entityRegistration", {}) or {}
        uei = reg.get("ueiSAM")
        out = []
        if uei:
            out.append(ClaimDict("uei", uei, None, "sam_gov", 0.9))
        if reg.get("legalBusinessName"):
            out.append(ClaimDict("legal_name", reg["legalBusinessName"], None, "sam_gov", 0.9))
        addr = ((e.get("coreData") or {}).get("physicalAddress") or {})
        astr = " ".join(str(addr.get(k, "")) for k in ("addressLine1", "city", "stateOrProvinceCode", "countryCode")).strip()
        if astr:
            out.append(ClaimDict("address", astr, None, "sam_gov", 0.85))
        return out
