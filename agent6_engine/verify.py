"""Verifikations-Loop Pass 1 — Multi-Quellen-Abgleich.

Sammelt Claims mehrerer Konnektoren zu einer Organisation, schreibt sie mit
Provenienz in die DB und vergibt Confidence NUR bei Mehrfachbestätigung durch
unabhängige Primärquellen. Quelle-agnostisch: jeder Konnektor liefert ClaimDicts.

Offline testbar: statt Live-Konnektoren kann eine Liste von Objekten mit
.fetch(...)-Methode injiziert werden, die gecannte ClaimDicts zurückgibt.
"""
from __future__ import annotations
import datetime as dt
from collections import defaultdict
from .db import Claim, Organization


def verify_org(session, org: Organization, connectors, *, vat=None) -> dict:
    all_claims = []
    for c in connectors:
        try:
            res = c.fetch(name=org.canonical_name, country=org.country, vat=vat or org.vat)
        except Exception:
            res = []
        for cd in res:
            all_claims.append((c, cd))

    # Claims persistieren
    for c, cd in all_claims:
        session.add(Claim(subject_type="organization", subject_id=org.id, predicate=cd.predicate,
                          object_value=cd.value, source_url=cd.source_url,
                          source_type=cd.source_type, method=getattr(c, "name", "connector"),
                          confidence=cd.confidence))

    # Corroboration: wie viele UNABHÄNGIGE Primärquellen bestätigen Identität?
    by_pred = defaultdict(set)
    for c, cd in all_claims:
        if cd.value and getattr(c, "is_primary", False):
            by_pred[cd.predicate].add(cd.source_type)
    id_preds = ("legal_name", "address", "lei", "company_number", "vat_valid")
    primary_sources = set()
    for p in id_preds:
        primary_sources |= by_pred.get(p, set())
    n_primary = len(primary_sources)

    # Starke Schlüssel aus Claims nachtragen
    strong = {cd.predicate: cd.value for c, cd in all_claims if cd.predicate in ("lei",) and cd.value}
    if strong.get("lei") and not org.lei:
        org.lei = strong["lei"]

    # Confidence-Regel: >=2 unabhängige Primärquellen -> verifiziert
    if n_primary >= 2:
        org.confidence = min(1.0, 0.6 + 0.2 * n_primary)
        verdict = "verifiziert"
    elif n_primary == 1:
        org.confidence = 0.5
        verdict = "einzelquelle"
    else:
        org.confidence = max(org.confidence, 0.2)
        verdict = "unbestätigt"
    org.last_verified = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return {"org": org.canonical_name, "verdict": verdict,
            "primary_sources": sorted(primary_sources), "claims_written": len(all_claims),
            "confidence": round(org.confidence, 2)}
