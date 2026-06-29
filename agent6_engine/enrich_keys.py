"""enrich_keys — starke Schlüssel/Attribute für alle Organisationen holen.

Läuft die Discovery-Primärquellen (GLEIF→LEI, Companies House→UK-Nr.,
Wikidata→Website/Land) über jede Organisation, schreibt Claims mit Provenienz
und trägt LEI/Domain/Adresse nach. Danach SICHERES Re-Mergen über starke Schlüssel.

Methodischer Hinweis: VIES ist ein *Validator* (VAT rein → gültig/Name raus),
kein Entdecker — es läuft nur, wenn eine VAT bereits bekannt ist. Deshalb ist es
NICHT Teil der Discovery-Konnektoren unten.
"""
from __future__ import annotations
import time
from sqlalchemy import select, func
from .db import Organization, Claim
from .connectors import EU_CONNECTORS, US_CONNECTORS
from .entity_resolution import reresolve_by_strong_keys


def default_connectors(region="eu"):
    classes = US_CONNECTORS if str(region).lower() == "us" else EU_CONNECTORS
    return [c() for c in classes]


def enrich_all(session, connectors=None, limit=None, sleep=0.2, live=True, region="eu") -> dict:
    conns = connectors if connectors is not None else default_connectors(region)
    orgs = list(session.scalars(select(Organization).order_by(Organization.id)))
    if limit:
        orgs = orgs[:limit]
    stats = {"processed": 0, "lei_found": 0, "domain_found": 0, "claims": 0}
    for org in orgs:
        for c in conns:
            try:
                res = c.fetch(name=org.canonical_name, country=org.country, vat=org.vat)
            except Exception:
                res = []
            for cd in res:
                session.add(Claim(subject_type="organization", subject_id=org.id, predicate=cd.predicate,
                                  object_value=cd.value, source_url=cd.source_url, source_type=cd.source_type,
                                  method=getattr(c, "name", "conn"), confidence=cd.confidence))
                stats["claims"] += 1
                if cd.predicate == "lei" and cd.value and not org.lei:
                    org.lei = cd.value; stats["lei_found"] += 1
                if cd.predicate == "domain" and cd.value and not org.domain:
                    org.domain = cd.value; stats["domain_found"] += 1
                if cd.predicate == "address" and cd.value and not org.address:
                    org.address = cd.value
            if live and sleep:
                time.sleep(sleep)
        stats["processed"] += 1
        if stats["processed"] % 50 == 0:
            session.commit()
    session.commit()
    return stats


def run(session, connectors=None, limit=None, live=True, region="eu") -> dict:
    before = session.scalar(select(func.count(Organization.id)))
    est = enrich_all(session, connectors=connectors, limit=limit, live=live, region=region)
    rr = reresolve_by_strong_keys(session)
    after = session.scalar(select(func.count(Organization.id)))
    result = {"orgs_before": before, "orgs_after": after,
              "merged_by_strong_key": rr["merged"], **est}
    print("ENRICH+RERESOLVE:", result)
    return result
