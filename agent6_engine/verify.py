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


# ---------------------------------------------------------------- DB-basierter Verify
import re as _re
from sqlalchemy import select as _select, delete as _delete

_PLZ = _re.compile(r"\b(\d{4,5})\b")


def _plz(a):
    m = _PLZ.search(str(a or ""))
    return m.group(1) if m else None


def _city_tokens(a):
    s = _re.sub(r"[^a-zäöüß ]", " ", str(a or "").lower())
    return {t for t in s.split() if len(t) >= 4}


def addresses_agree(a, b) -> bool:
    """Tolerant: gleiche PLZ ODER hinreichende Ort-Token-Überschneidung."""
    pa, pb = _plz(a), _plz(b)
    if pa and pb:
        return pa == pb
    ta, tb = _city_tokens(a), _city_tokens(b)
    return bool(ta & tb) and len(ta & tb) / max(1, len(ta | tb)) >= 0.3


def verify_all(session) -> dict:
    """Kreuzt die BEREITS in der DB liegenden Claims (aus enrich) gegen einander.
    Adresse gilt als verifiziert, wenn >=2 unabhängige Quellen sie liefern UND
    sie übereinstimmen (PLZ/Ort). Setzt org.confidence + last_verified. Idempotent."""
    session.execute(_delete(Claim).where(Claim.source_type == "verify"))
    stats = {"orgs": 0, "addr_2plus_sources": 0, "addr_verified": 0, "addr_conflict": 0,
             "id_verified": 0, "single_source": 0, "unconfirmed": 0}
    orgs = session.scalars(_select(Organization)).all()
    for org in orgs:
        stats["orgs"] += 1
        claims = session.scalars(_select(Claim).where(
            Claim.subject_type == "organization", Claim.subject_id == org.id)).all()
        addr_by_src, primary_id_sources = {}, set()
        for cl in claims:
            if cl.predicate == "address" and cl.object_value:
                addr_by_src.setdefault(cl.source_type, cl.object_value)
            if cl.predicate in ("lei", "legal_name", "address", "company_number", "vat_valid") and cl.object_value:
                primary_id_sources.add(cl.source_type)
        # Adress-Corroboration
        srcs = list(addr_by_src.values())
        if len(srcs) >= 2:
            stats["addr_2plus_sources"] += 1
            agree = any(addresses_agree(srcs[i], srcs[j])
                        for i in range(len(srcs)) for j in range(i + 1, len(srcs)))
            if agree:
                stats["addr_verified"] += 1
                session.add(Claim(subject_type="organization", subject_id=org.id,
                                  predicate="address_verified", object_value="true",
                                  source_type="verify", method="verify", confidence=0.95))
            else:
                stats["addr_conflict"] += 1
        # Org-Confidence aus #unabhängigen Primärquellen
        n = len(primary_id_sources)
        if n >= 2:
            org.confidence = min(1.0, 0.6 + 0.2 * n); stats["id_verified"] += 1
        elif n == 1:
            org.confidence = max(org.confidence, 0.5); stats["single_source"] += 1
        else:
            stats["unconfirmed"] += 1
        org.last_verified = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return stats
