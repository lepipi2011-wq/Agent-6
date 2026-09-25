"""Objekt-zentrierter Bild-Harvester: Junk-Filter, Dedup, Quality-Gate, Airtable-Record."""
from agent6_engine import image_search_harvester as H


class FakePattern:
    def __init__(self, img_query, segment="seg"):
        self.img_query = img_query; self.text_terms = ""; self.segment = segment


class FakeSearcher:
    def __init__(self, results): self.results = results; self.calls = []
    def search(self, q, n=15): self.calls.append(q); return self.results


class FakeWriter:
    enabled = True
    def __init__(self, existing=None): self._ex = set(existing or []); self.written = []
    def existing_urls(self): return set(self._ex)
    def write(self, records): self.written.extend(records); return len(records)


def test_is_junk():
    assert H.is_junk("https://www.pinterest.com/x.jpg")
    assert H.is_junk("https://shutterstock.com/x.jpg")
    assert not H.is_junk("https://www.liebherr.com/machine.jpg")


def test_build_record_pattern_mapping():
    rec = H.build_record({"url": "https://liebherr.com/a.jpg", "query": "q", "source": "liebherr"}, "P4")
    assert rec["Pattern-Vorschlag"] == "P4 Joystick-Kabine + Display"
    assert rec["Bild"] == [{"url": "https://liebherr.com/a.jpg"}]
    assert rec["Status"] == "Neu"


def test_harvest_filters_and_dedups(tmp_path):
    results = [
        {"url": "https://liebherr.com/good1.jpg", "source": "liebherr"},
        {"url": "https://pinterest.com/junk.jpg", "source": "pinterest"},
        {"url": "https://casagrande.it/rig.jpg", "source": "casagrande"},
        {"url": "https://dup.com/x.jpg", "source": "dup"},
    ]
    s = FakeSearcher(results); w = FakeWriter(existing=["https://dup.com/x.jpg"])
    pats = {"P4": FakePattern("tracked drilling rig")}
    res = H.harvest({}, pats, per_pattern=10, searcher=s, writer=w,
                    manifest_path=str(tmp_path / "m.json"))
    assert res["new"] == 2 and res["junk"] == 1 and res["dup"] == 1
    assert res["airtable_written"] == 2
    assert res["by_pattern"]["P4"] == 2
    urls = {r["Bild-URL"] for r in w.written}
    assert urls == {"https://liebherr.com/good1.jpg", "https://casagrande.it/rig.jpg"}


def test_only_patterns(tmp_path):
    s = FakeSearcher([{"url": "https://x.com/a.jpg", "source": "x"}]); w = FakeWriter()
    pats = {"P4": FakePattern("q4"), "P5": FakePattern("q5")}
    res = H.harvest({}, pats, searcher=s, writer=w, only_patterns=["P5"],
                    manifest_path=str(tmp_path / "m.json"))
    assert res["by_pattern"] == {"P5": 1} and "P4" not in res["by_pattern"]


def test_quality_gate_warns_on_low_yield():
    qg = H.quality_gate({"found": 100, "new": 10})
    assert qg["yield"] == 0.1 and qg["quality_warning"]
    qg2 = H.quality_gate({"found": 100, "new": 80})
    assert qg2["quality_warning"] is None
