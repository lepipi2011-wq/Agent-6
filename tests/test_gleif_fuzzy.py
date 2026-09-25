"""Tests für das Fuzzy-GLEIF-Matching — Kernrisiko: falsche LEIs abweisen."""
from agent6_engine.connectors.gleif import GLEIFConnector, _sim


def _record(lei, name, country="AT", status="ACTIVE"):
    return {"data": {"id": lei, "attributes": {"lei": lei, "entity": {
        "legalName": {"name": name},
        "legalAddress": {"city": "Linz", "country": country},
        "status": status}}}}


def test_similarity():
    assert _sim("Rubble Master", "RUBBLE MASTER HMH GMBH") >= 0.6      # Marke -> Rechtsträger
    assert _sim("Bergmann Maschinenbau", "Bergmann Trucking Inc") < 0.6  # anderer Betrieb


def test_exact_parse_still_works():
    claims = GLEIFConnector().parse(_record("529900T8BM49AURSDO55", "Rubble Master HMH GmbH"))
    assert any(c.predicate == "lei" and c.value == "529900T8BM49AURSDO55" for c in claims)
    assert all(c.confidence >= 0.9 for c in claims if c.predicate == "lei")   # exakt = hohe Confidence


def test_fuzzy_best_candidate_selection():
    conn = GLEIFConnector()
    payload = {"data": [
        {"attributes": {"value": "RUBBLE MASTER HMH GMBH"},
         "relationships": {"lei-records": {"data": {"id": "GOOD-LEI"}}}},
        {"attributes": {"value": "RUBBLE TRUCKING LLC"},
         "relationships": {"lei-records": {"data": {"id": "BAD-LEI"}}}},
    ]}
    assert conn._best_fuzzy("Rubble Master", payload) == "GOOD-LEI"
    # gar kein ähnlicher Kandidat -> nichts akzeptieren
    weak = {"data": [{"attributes": {"value": "Völlig Andere AG"},
                      "relationships": {"lei-records": {"data": {"id": "X"}}}}]}
    assert conn._best_fuzzy("Rubble Master", weak) is None


def test_fuzzy_country_guard():
    conn = GLEIFConnector()
    rec = _record("LEI1", "Rubble Master HMH GmbH", country="AT")["data"]
    # Land passt -> akzeptiert, aber niedrigere Confidence als exakt
    ok = conn._parse_record(rec, query_name="Rubble Master", country="AT", fuzzy=True)
    assert any(c.predicate == "lei" for c in ok)
    assert [c.confidence for c in ok if c.predicate == "lei"][0] < 0.9
    # Land passt NICHT -> komplett abgelehnt (kein falscher LEI)
    bad = conn._parse_record(rec, query_name="Rubble Master", country="US", fuzzy=True)
    assert bad == []
