"""FCC ID — Funk-Zulassung (belegt 'Funk vorhanden'), US-spezifisch.

Hinweis: Die FCC bietet keine einheitliche offizielle JSON-Suche nach Firma.
Diese Klasse ist gegen eine konfigurierbare Quelle (fcc_id.endpoint) gebaut, die
ein JSON {"results":[{"fcc_id","applicant","product"}]} liefert (z.B. interner
Spiegel oder fccid.io-artige API). parse() ist quellenunabhängig testbar.
"""
from __future__ import annotations
import requests
from .base import Connector, ClaimDict


class FCCIDConnector(Connector):
    name = "fcc_id"; source_type = "fcc_id"; is_primary = True; needs_key = False

    def __init__(self, endpoint=None):
        self.endpoint = endpoint  # z.B. "https://.../search?applicant={name}"

    def fetch(self, *, name, country=None, **kw):
        if not self.endpoint:
            return []
        try:
            r = requests.get(self.endpoint.format(name=requests.utils.quote(name)), timeout=20)
            r.raise_for_status()
            return self.parse(r.json())
        except Exception:
            return []

    def parse(self, payload):
        res = (payload or {}).get("results") or []
        if not res:
            return []
        first = res[0]
        fid = first.get("fcc_id")
        url = f"https://fccid.io/{fid}" if fid else None
        out = [ClaimDict("funk_present", "true", url, "fcc_id", 0.85)]
        if fid:
            out.append(ClaimDict("fcc_id", fid, url, "fcc_id", 0.85))
        if first.get("product"):
            out.append(ClaimDict("fcc_product", first["product"], url, "fcc_id", 0.7))
        return out
