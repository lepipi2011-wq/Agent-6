"""AirtableWriter-Robustheit: transiente Netz-/DNS-Fehler werden geretryt,
dauerhafte Fehler werden gezaehlt (write_failures) und NICHT still verschluckt."""
import requests
from agent6_engine.image_search_harvester import AirtableWriter


class FakeResp:
    def __init__(self, status=200, records=None):
        self.status_code = status
        self._records = records or []
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            e.response = self
            raise e

    def json(self):
        return {"records": self._records}


def _writer():
    w = AirtableWriter(token="x")
    w._sleep = lambda *a, **k: None   # kein echtes Warten im Test
    w.retry_backoff = 0
    # Match-Ziel fuer update_enrichment (statt echtem Airtable-Read)
    w._all_records = lambda: [{"id": "rec1", "fields": {"Bild-URL": "https://a.com/x.jpg"}}]
    return w


def test_write_retries_then_succeeds(monkeypatch):
    w = _writer()
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:                      # zweimal DNS-Fehler, dann Erfolg
            raise requests.exceptions.ConnectionError("getaddrinfo failed")
        return FakeResp(200, [{"id": "rec1"}])

    monkeypatch.setattr(requests, "request", fake_request)
    done = w.update_enrichment([{"bild_url": "https://a.com/x.jpg", "oem": "Bandit"}])
    assert done == 1
    assert w.write_failures == 0
    assert calls["n"] == 3                       # 2 Fehlversuche + 1 Erfolg


def test_write_persistent_failure_is_counted(monkeypatch):
    w = _writer()
    w.max_retries = 2

    def boom(method, url, **kw):
        raise requests.exceptions.ConnectionError("dns down")

    monkeypatch.setattr(requests, "request", boom)
    done = w.update_enrichment([{"bild_url": "https://a.com/x.jpg", "oem": "Bandit"}])
    assert done == 0
    assert w.write_failures == 1                 # nicht still verschluckt
    assert "ConnectionError" in w.last_error


def test_preis_eur_wird_als_string_geschrieben(monkeypatch):
    """Preis-EUR ist in Airtable eine Text-Spalte -> Zahl muss als String gesendet werden,
    sonst 422 INVALID_VALUE_FOR_COLUMN und der ganze Batch kippt."""
    w = _writer()
    sent = {}

    def fake_request(method, url, **kw):
        sent["fields"] = kw["json"]["records"][0]["fields"]
        return FakeResp(200, [{"id": "rec1"}])

    monkeypatch.setattr(requests, "request", fake_request)
    w.update_enrichment([{"bild_url": "https://a.com/x.jpg", "oem": "Bandit", "preis_eur": 3594}])
    assert sent["fields"]["Preis-EUR"] == "3594"          # String, nicht 3594 (int)
    assert isinstance(sent["fields"]["Preis-EUR"], str)


def test_preis_eur_none_wird_leerstring(monkeypatch):
    w = _writer()
    sent = {}

    def fake_request(method, url, **kw):
        sent["fields"] = kw["json"]["records"][0]["fields"]
        return FakeResp(200, [{"id": "rec1"}])

    monkeypatch.setattr(requests, "request", fake_request)
    w.update_enrichment([{"bild_url": "https://a.com/x.jpg", "oem": "Bandit", "preis_eur": None}])
    assert sent["fields"]["Preis-EUR"] == ""


def test_422_is_not_retried_but_counted(monkeypatch):
    w = _writer()
    calls = {"n": 0}

    def fake_request(method, url, **kw):
        calls["n"] += 1
        return FakeResp(422)                      # Feldname falsch -> echter Datenfehler

    monkeypatch.setattr(requests, "request", fake_request)
    done = w.update_enrichment([{"bild_url": "https://a.com/x.jpg", "oem": "Bandit"}])
    assert done == 0
    assert w.write_failures == 1
    assert calls["n"] == 1                        # KEIN Retry bei 4xx
