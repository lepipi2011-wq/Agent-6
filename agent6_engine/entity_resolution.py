"""Entity-Resolution — konservativ, auditierbar.

Auto-Merge NUR bei sicheren Signalen (starke Schlüssel LEI/VAT/HR oder norm-exakt).
Schwache Signale (Substring / Brand-Token) werden NICHT automatisch gemerged, sondern
als MergeCandidate zur Mensch-Review protokolliert. Präzision vor Recall:
lieber ein Duplikat behalten als einen echten OEM still verlieren.
"""
from __future__ import annotations
import re
from sqlalchemy import select
from .db import Organization, MergeCandidate

WHITELIST = [
    ("rapid maschinenfabrik", "rapid technic"),
    ("lindner traktoren", "lindner recyclingtech"),
]
REVIEW_MIN_SCORE = 0.34   # unterhalb: gar kein Kandidat


def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def brand_tokens(name) -> set[str]:
    n = norm(name)
    n = re.sub(r"\b(gmbh|ag|inc|ltd|llc|srl|spa|s\.p\.a|s\.r\.l|co|kg|bv|oy|ab|as|sa|plc|corp|group|holding)\b", "", n)
    n = re.sub(r"\(.*?\)", "", n)
    return {t for t in re.split(r"[^a-z0-9]+", n) if len(t) >= 3}


def _whitelisted(a, b) -> bool:
    na, nb = norm(a), norm(b)
    return any((x in na and y in nb) or (y in na and x in nb) for x, y in WHITELIST)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify(session, name, country=None, lei=None, vat=None, hr_number=None):
    """Rueckgabe (org|None, tier, reason, score).
    tier in {strong, norm, substring, brand, none}."""
    for key, val in (("lei", lei), ("vat", vat), ("hr_number", hr_number)):
        if val:
            hit = session.scalar(select(Organization).where(getattr(Organization, key) == val))
            if hit:
                return hit, "strong", f"strong-key:{key}", 1.0
    nn = norm(name)
    q = select(Organization).where(Organization.norm_name == nn)
    if country:
        q = q.where((Organization.country == country) | (Organization.country.is_(None)))
    hit = session.scalar(q)
    if hit:
        return hit, "norm", "norm-exakt", 1.0
    # schwache Signale: besten Kandidaten finden, aber NICHT mergen
    bt = brand_tokens(name)
    best = (None, "none", "neu", 0.0)
    for org in session.scalars(select(Organization)):
        en = org.norm_name or norm(org.canonical_name)
        if _whitelisted(name, org.canonical_name):
            continue
        if len(nn) >= 5 and len(en) >= 5 and (nn in en or en in nn):
            score = min(len(nn), len(en)) / max(len(nn), len(en))
            if score > best[3]:
                best = (org, "substring", f"substring~{en[:24]}", round(score, 2))
        j = _jaccard(bt, brand_tokens(org.canonical_name))
        if j >= REVIEW_MIN_SCORE and j > best[3]:
            best = (org, "brand", f"brand-token~{en[:24]}", round(j, 2))
    return best


def upsert_org(session, name, country=None, lei=None, vat=None, hr_number=None,
               domain=None, status=None, address=None):
    """Findet oder legt an. Rueckgabe (org, outcome) mit outcome in
    {merged-strong, merged-norm, review, created}."""
    org, tier, reason, score = classify(session, name, country, lei, vat, hr_number)
    if tier in ("strong", "norm"):
        for attr, val in (("lei", lei), ("vat", vat), ("hr_number", hr_number),
                          ("domain", domain), ("address", address), ("status", status)):
            if val and not getattr(org, attr):
                setattr(org, attr, val)
        return org, f"merged-{tier}"
    # schwacher Match -> neue Entitaet ANLEGEN + Review-Kandidat loggen
    new = Organization(canonical_name=str(name).strip(), norm_name=norm(name), country=country,
                       lei=lei, vat=vat, hr_number=hr_number, domain=domain, status=status, address=address)
    session.add(new)
    session.flush()
    if org is not None and tier in ("substring", "brand"):
        session.add(MergeCandidate(new_org_id=new.id, matched_org_id=org.id,
                                   new_name=new.canonical_name, matched_name=org.canonical_name,
                                   tier=tier, reason=reason, score=score))
        return new, "review"
    return new, "created"


def reresolve_by_strong_keys(session):
    """Nachträgliches, SICHERES Mergen: Organisationen mit identischem LEI/VAT/HR
    werden zusammengeführt (abhängige Claims/Models/Contacts umgehängt, Duplikat
    gelöscht, Merge im Log als decision='merge'/tier='strong' vermerkt)."""
    from sqlalchemy import select, update, func
    from .db import Organization, Claim, Model, Contact, MergeCandidate
    merged = 0
    for keyattr in ("lei", "vat", "hr_number"):
        col = getattr(Organization, keyattr)
        groups = session.execute(
            select(col, func.count(Organization.id)).where(col.is_not(None))
            .group_by(col).having(func.count(Organization.id) > 1)).all()
        for keyval, _cnt in groups:
            orgs = list(session.scalars(select(Organization).where(col == keyval).order_by(Organization.id)))
            survivor = orgs[0]
            for dup in orgs[1:]:
                merge_orgs(session, survivor, dup, tier="strong", reason=f"{keyattr}={keyval}")
                merged += 1
        session.commit()
    return {"merged": merged}


def merge_orgs(session, survivor, dup, tier="manual", reason=""):
    """Führt dup in survivor: hängt Claims/Models/Contacts um, überträgt fehlende
    Felder, protokolliert den Merge und löscht das Duplikat. Zentrale Merge-Logik
    für Re-Resolve UND die manuelle Review-Rückspielung."""
    from sqlalchemy import update as _update
    from .db import Claim as _Claim, Model as _Model, Contact as _Contact, MergeCandidate as _MC
    if survivor.id == dup.id:
        return
    session.execute(_update(_Claim).where(_Claim.subject_type == "organization",
                    _Claim.subject_id == dup.id).values(subject_id=survivor.id))
    session.execute(_update(_Model).where(_Model.organization_id == dup.id)
                    .values(organization_id=survivor.id))
    session.execute(_update(_Contact).where(_Contact.organization_id == dup.id)
                    .values(organization_id=survivor.id))
    for a in ("domain", "address", "vat", "hr_number", "lei"):
        if not getattr(survivor, a) and getattr(dup, a):
            setattr(survivor, a, getattr(dup, a))
    session.add(_MC(new_org_id=survivor.id, matched_org_id=dup.id,
                    new_name=dup.canonical_name, matched_name=survivor.canonical_name,
                    tier=tier, reason=reason, score=1.0, decision="merge"))
    session.delete(dup)
