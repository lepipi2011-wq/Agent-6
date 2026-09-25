"""Offline-Test für Discovery: Fake-Suche + Fake-Gate, keine Netz-/Key-Nutzung."""
from dataclasses import dataclass
from agent6_engine import db, discovery
from agent6_engine.entity_resolution import upsert_org


@dataclass
class P:
    code: str = "P4"
    text_terms: str = "forestry mulcher tracked carrier"
    segment: str = "Forestry"
    name: str = "Forestry"


class FakeSearcher:
    """Liefert feste Treffer: 1 bekannter OEM, 1 neuer OEM, 1 Aggregator (Junk)."""
    def search(self, query, n=8):
        return [
            {"title": "Existing Co - Products", "link": "https://existing-co.de/x", "snippet": "tracked mulcher"},
            {"title": "Neu Raupen GmbH | Home", "link": "https://neu-raupen.de", "snippet": "Raupen-Mulcher mit Funk"},
            {"title": "Used machines", "link": "https://www.mascus.com/listing", "snippet": "marketplace"},
        ]


class KeepAllGate:
    def keep(self, name, text, cls, patterns):
        return True, "test"


class RejectGate:
    def keep(self, name, text, cls, patterns):
        return False, "out-of-scope"


def _session_with_existing():
    s = db.init_db(db.make_engine("sqlite:///:memory:"))()
    upsert_org(s, "Existing Co", domain="https://existing-co.de")
    s.commit()
    return s


def test_extract_drops_aggregators():
    assert discovery.extract_candidate({"link": "https://www.mascus.com/x", "title": "X"}) is None
    ok = discovery.extract_candidate({"link": "https://neu-raupen.de", "title": "Neu Raupen GmbH | Home"})
    assert ok and ok["domain"] == "https://neu-raupen.de"


def test_discover_dedup_and_new():
    s = _session_with_existing()
    res = discovery.discover(s, {"harvest": {"request_timeout": 5}, "search": {}},
                             {"P4": P()}, searcher=FakeSearcher(), gate=KeepAllGate())
    # Existing Co -> bekannt (skip); Neu Raupen -> neu; mascus -> Junk (raus)
    assert res["known_skipped"] >= 1
    assert res["new"] == 1
    from sqlalchemy import select, func
    from agent6_engine.db import Organization
    # neue candidate-Org wurde geschrieben
    assert s.scalar(select(func.count()).select_from(Organization)) == 2


def test_discover_gate_rejects():
    s = _session_with_existing()
    res = discovery.discover(s, {"harvest": {"request_timeout": 5}, "search": {}},
                             {"P4": P()}, searcher=FakeSearcher(), gate=RejectGate())
    assert res["new"] == 0 and res["gate_rejected"] >= 1


def test_quality_gate_math():
    q = discovery.quality_gate_discovery(
        {"new": 1, "known_skipped": 9, "candidates": 10, "gate_rejected": 8, "gate_inactive": 0})
    assert q["yield"] == 0.1 and q["quality_warning"]      # Yield 10% < 30% -> Warnung
