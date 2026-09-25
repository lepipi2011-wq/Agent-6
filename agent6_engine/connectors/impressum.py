"""Impressum-Konnektor (DACH) — GF, USt-IdNr, Adresse aus der Pflichtseite.
Gratis Primärquelle für DE/AT/CH. parse(html) ist netzwerkfrei.
"""
from __future__ import annotations
import re, requests
from .base import Connector, ClaimDict

_PATHS = ("/impressum", "/de/impressum", "/kontakt/impressum", "/imprint", "/legal-notice")
_VAT = re.compile(r"(USt[- ]?IdNr\.?|VAT|MwSt)\s*[:.]?\s*([A-Z]{2}\s?\d[\d\s]{6,})", re.I)
_GF = re.compile(r"(Gesch[äa]ftsf[üu]hrer(?:in)?)\s*[:.]?\s*([A-ZÄÖÜ][\w.\-]+(?:\s+[A-ZÄÖÜ][\w.\-]+){0,3})")
_ADDR = re.compile(
    r"([A-ZÄÖÜ][\wäöüß.\- ]{2,40}(?:stra[ßs]{1,2}e|str\.|weg|allee|platz|ring|gasse)\s*\d+[a-z]?)"
    r"[,\s]+(\d{5})\s+([A-ZÄÖÜ][\wäöüß.\- ]{1,40})", re.I)


class ImpressumConnector(Connector):
    name = "impressum"; source_type = "impressum"; is_primary = True; needs_key = False

    def fetch(self, *, name=None, country=None, domain=None, **kw):
        if not domain:
            return []
        base = domain.rstrip("/")
        for p in _PATHS:
            try:
                r = requests.get(base + p, timeout=15, headers={"User-Agent": "Agent6/1.0"}, verify=False)
                if r.status_code == 200 and "impress" in r.text.lower() or "USt" in r.text:
                    return self.parse(r.text, url=base + p)
            except Exception:
                continue
        return []

    def parse(self, html, url=None):
        out = []
        m = _VAT.search(html or "")
        if m:
            out.append(ClaimDict("vat", re.sub(r"\s+", "", m.group(2)), url, "impressum", 0.85))
        g = _GF.search(html or "")
        if g:
            out.append(ClaimDict("managing_director", g.group(2).strip(), url, "impressum", 0.8))
        a = _ADDR.search(html or "")
        if a:
            addr = f"{a.group(1).strip()}, {a.group(2)} {a.group(3).strip()}"
            out.append(ClaimDict("address", " ".join(addr.split()), url, "impressum", 0.8))
        return out
