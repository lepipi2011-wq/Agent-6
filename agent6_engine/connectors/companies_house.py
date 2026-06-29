"""Companies House (UK) — Register-Suche (gratis, benötigt freien API-Key).

Discovery + Verifikation für UK-OEMs. parse() ist netzwerkfrei.
Key via env COMPANIES_HOUSE_KEY (Basic-Auth, Passwort leer).
"""
from __future__ import annotations
import os
import requests
from .base import Connector, ClaimDict

API = "https://api.company-information.service.gov.uk/search/companies"


class CompaniesHouseConnector(Connector):
    name = "companies_house"
    source_type = "register"
    is_primary = True
    needs_key = True

    def __init__(self, key_env="COMPANIES_HOUSE_KEY"):
        self.key = os.environ.get(key_env, "")

    def fetch(self, *, name, country=None, **kw) -> list[ClaimDict]:
        if country and country != "UK":
            return []
        if not self.key:
            return []
        try:
            r = requests.get(API, params={"q": name, "items_per_page": 1},
                             auth=(self.key, ""), timeout=20)
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload) -> list[ClaimDict]:
        items = (payload or {}).get("items") or []
        if not items:
            return []
        it = items[0]
        num = it.get("company_number")
        url = f"https://find-and-update.company-information.service.gov.uk/company/{num}" if num else None
        out = [ClaimDict("company_number", num, url, "register", 0.9),
               ClaimDict("registration_status", it.get("company_status"), url, "register", 0.9)]
        if it.get("title"):
            out.append(ClaimDict("legal_name", it["title"], url, "register", 0.9))
        if it.get("address_snippet"):
            out.append(ClaimDict("address", it["address_snippet"], url, "register", 0.85))
        return out
