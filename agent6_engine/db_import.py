"""Master -> DB. Liest den bestehenden Master (header-basiert) und lädt
Organisationen (via Entity-Resolution), Patterns und Provenienz-Claims.
"""
from __future__ import annotations
from . import master_io as M
from .db import Pattern, Model, Claim, Organization
from sqlalchemy import select
from .entity_resolution import upsert_org, norm


def import_master(session, cfg) -> dict:
    wb = M.open_master(cfg)
    patterns = M.read_patterns(wb, cfg)
    seeds = M.read_seeds(wb, cfg, patterns)
    wb.close()

    # Patterns
    for code, p in patterns.items():
        if not session.get(Pattern, code):
            session.add(Pattern(code=code, img_query=str(p.img_query or "") or None,
                                text_terms=str(p.text_terms or "") or None,
                                ref_oem=str(p.ref_oem or "") or None,
                                segment=str(p.segment or "") or None))
    session.flush()

    created = {"merged-strong": 0, "merged-norm": 0, "review": 0, "created": 0}
    claims = 0
    for s in seeds:
        org, outcome = upsert_org(session, s.oem, country=s.land, domain=s.domain, status="unknown")
        created[outcome] = created.get(outcome, 0) + 1
        # Provenienz-Claims aus dem Master
        if s.domain:
            session.add(Claim(subject_type="organization", subject_id=org.id, predicate="domain",
                              object_value=s.domain, source_url=s.link, source_type="master",
                              method="master_import", confidence=0.6)); claims += 1
        if s.pattern:
            session.add(Claim(subject_type="organization", subject_id=org.id, predicate="pattern",
                              object_value=s.pattern, source_type="master",
                              method="master_import", confidence=0.5)); claims += 1
            session.add(Model(name=s.segment or s.oem, organization_id=org.id,
                              pattern_code=s.pattern, segment=s.segment))
    session.commit()
    from sqlalchemy import func
    orgs_total = session.scalar(select(func.count(Organization.id)))
    return {"seeds": len(seeds),
            "auto_merged_strong": created["merged-strong"],
            "auto_merged_norm": created["merged-norm"],
            "review_candidates": created["review"],
            "distinct_new": created["created"],
            "orgs_total": orgs_total,
            "patterns": len(patterns), "claims": claims}
