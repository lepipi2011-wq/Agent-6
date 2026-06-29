"""Offline-Smoke-Tests — kein Netz, keine Master-Datei nötig.
Prüfen die reine Logik: Klassen-Normalisierung, Entity-Resolution,
VLM-Verdikt-Parsing, Konnektor-Parser, DB-Schema.
"""
from agent6_engine.master_io import normalize_class
from agent6_engine.vlm_filter import parse_verdict
from agent6_engine import db, entity_resolution as er
from agent6_engine.connectors import GLEIFConnector, VIESConnector, CompaniesHouseConnector


def test_normalize_class():
    assert normalize_class("P4 Forestry") == "P4"
    assert normalize_class("—Adjacent (AGV/SPMT/Schreitbagger)") == "out_scope"
    assert normalize_class("") == "unknown"
    assert normalize_class("out_scope") == "out_scope"   # idempotent


def test_vlm_parse_verdict():
    assert parse_verdict('{"keep": false, "reason": "Turbine"}')[0] is False
    assert parse_verdict('{"keep": true, "reason": "Raupenkran"}')[0] is True
    assert parse_verdict("keep=false")[0] is False


def test_entity_resolution_strong_key():
    eng = db.make_engine("sqlite:///:memory:")
    session = db.init_db(eng)()
    org, out = er.upsert_org(session, "Rubble Master", country="AT", lei="ABC123")
    assert out == "created"
    # gleicher LEI -> starker-Schlüssel-Merge (kein Duplikat)
    org2, out2 = er.upsert_org(session, "Rubble Master HMH GmbH", country="AT", lei="ABC123")
    assert out2 == "merged-strong" and org2.id == org.id
    session.close()


def test_connector_parsers_offline():
    g = GLEIFConnector().parse({"data": [{"id": "X", "attributes": {
        "lei": "X", "entity": {"legalName": {"name": "ACME"},
        "legalAddress": {"city": "Linz", "country": "AT"}, "status": "ACTIVE"}}}]})
    assert any(c.predicate == "lei" for c in g)
    v = VIESConnector().parse({"isValid": True, "name": "ACME", "address": "X"})
    assert any(c.predicate == "vat_valid" and c.value == "true" for c in v)
    ch = CompaniesHouseConnector().parse({"items": [{"company_number": "1",
        "company_status": "active", "title": "ACME LTD"}]})
    assert any(c.predicate == "company_number" for c in ch)
