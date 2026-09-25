"""Tests für die DB-basierte Verifikation: Adress-Abgleich + Mehrquellen-Corroboration."""
from agent6_engine import db, verify
from agent6_engine.entity_resolution import upsert_org
from agent6_engine.db import Claim
from agent6_engine.connectors.impressum import ImpressumConnector


def test_addresses_agree():
    assert verify.addresses_agree("Musterstr. 1, 84028 Landshut", "Musterstraße 1, 84028 Landshut")
    assert verify.addresses_agree("X, 12345 Berlin", "Y 12345 Berlin")          # gleiche PLZ
    assert not verify.addresses_agree("A, 84028 Landshut", "B, 10115 Berlin")    # andere Stadt+PLZ


def test_impressum_extracts_address():
    html = "Impressum. Musterstraße 12, 84028 Landshut. Geschäftsführer: Max Mustermann"
    claims = ImpressumConnector().parse(html, url="https://x.de/impressum")
    addr = [c.value for c in claims if c.predicate == "address"]
    assert addr and "84028" in addr[0]


def _org_with_claims(s, name, addrs):
    org, _ = upsert_org(s, name, country="DE")
    for src, val in addrs:
        s.add(Claim(subject_type="organization", subject_id=org.id, predicate="address",
                    object_value=val, source_type=src, method=src, confidence=0.9))
    s.commit()
    return org


def test_verify_marks_agreeing_address():
    s = db.init_db(db.make_engine("sqlite:///:memory:"))()
    _org_with_claims(s, "Agree Co", [("gleif", "Werkstr 5, 84028 Landshut"),
                                     ("impressum", "Werkstraße 5, 84028 Landshut")])
    _org_with_claims(s, "Conflict Co", [("gleif", "A, 10115 Berlin"),
                                        ("impressum", "B, 84028 Landshut")])
    res = verify.verify_all(s)
    assert res["addr_verified"] == 1 and res["addr_conflict"] == 1
    # 2. Lauf idempotent (keine doppelten verify-Claims)
    res2 = verify.verify_all(s)
    assert res2["addr_verified"] == 1
    s.close()
