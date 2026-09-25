"""Text-Harvester: Spec-Query-Bau, Term-Matching, Quellen-Score, 3-Metriken-Gate."""
from agent6_engine import text_harvester as T
from agent6_engine.master_io import PatternLite, load_patterns_json


class FakeP:
    def __init__(self, seg, ref_oem="", tt=""):
        self.segment = seg; self.ref_oem = ref_oem; self.text_terms = tt; self.img_query = ""


class FakeSearcher:
    def __init__(self, results): self.results = results
    def search(self, q, n=10): return self.results


def test_source_score():
    assert T.source_score("https://www.liebherr.com/x") == 3
    assert T.source_score("https://www.mascus.com/x") == 1
    assert T.source_score("https://khl.com/news") == 2


def test_matched_terms():
    m = T.matched_terms("Bagger mit Kettenfahrwerk und CAN-Bus, radio remote")
    assert "Kettenfahrwerk" in m and "CAN-Bus" in m and len(m) >= 3


def test_build_spec_queries():
    qs = T.build_spec_queries(FakeP("Mini crawler crane", ref_oem="Maeda MC-505 / Unic"))
    assert any("Kettenfahrwerk" in q for q in qs)
    assert any("Maeda" in q for q in qs)


def test_harvest_scores_and_dedups(tmp_path):
    results = [
        {"title": "Tracked crawler Kettenfahrwerk CAN remote", "url": "https://liebherr.com/a",
         "snippet": "radio remote control tracked undercarriage", "source": "liebherr"},
        {"title": "Used machine", "url": "https://mascus.com/x", "snippet": "for sale", "source": "mascus"},
        {"title": "dup", "url": "https://liebherr.com/b", "snippet": "x", "source": "liebherr"},  # gleiche Domain
    ]
    s = FakeSearcher(results)
    pats = {"P4": FakeP("tracked machine", ref_oem="Liebherr")}
    res = T.harvest({}, pats, searcher=s, out_csv=str(tmp_path / "t.csv"),
                    out_json=str(tmp_path / "t.json"))
    # liebherr (stark, score3) zählt, mascus (score1) zählt als found aber schwach, 2. liebherr = dup
    assert res["dup"] >= 1
    assert res["source_score"] >= 2.0
    assert "yield" in res and "ab_share" in res


def test_quality_gate_stop_on_two_breaches():
    g = T.quality_gate({"new": 100, "found": 100, "strong": 10, "score_sum": 150})
    # ab 10%<40% und score 1.5<2.0 -> zwei Verletzungen -> STOP
    assert "STOP" in g


def test_load_patterns_json(tmp_path):
    import json
    f = tmp_path / "patterns.json"
    json.dump([{"code": "P4", "img_query": "q", "segment": "s", "ref_oem": "o"}], open(f, "w"))
    pats = load_patterns_json(str(f))
    assert "P4" in pats and pats["P4"].img_query == "q"


def test_llm_judge_filters_components():
    """LLM-Urteilsschicht verwirft Bauteile, behält Maschinen — statt Keyword-Zählen."""
    results = [
        {"title": "CAN Bus Cable 2x2x0.75", "url": "https://fscables.com/can", "snippet": "cable datasheet", "source": "fscables"},
        {"title": "Raupenbagger RC-Serie", "url": "https://liebherr.com/crawler", "snippet": "Kettenbagger mit Kabine", "source": "liebherr"},
    ]
    s = FakeSearcher(results)

    def fake_judge(name, text, code):
        # simuliert Claude: Kabel raus, Maschine rein
        low = (name + text).lower()
        if "cable" in low or "can bus" in low:
            return (False, "Bauteil/Kabel")
        return (True, "Raupenmaschine")

    pats = {"P4": FakeP("tracked", ref_oem="")}
    res = T.harvest({}, pats, searcher=s, judge=fake_judge,
                    out_csv="/tmp/j.csv", out_json="/tmp/j.json")
    assert res["judged"] == 2 and res["llm_rejected"] == 1 and res["new"] == 1


def test_no_llm_keeps_all_nonjunk():
    results = [{"title": "x", "url": "https://liebherr.com/a", "snippet": "y", "source": "liebherr"}]
    s = FakeSearcher(results)
    res = T.harvest({}, {"P4": FakeP("t")}, searcher=s, use_llm=False,
                    out_csv="/tmp/n.csv", out_json="/tmp/n.json")
    assert res["new"] == 1 and res["judged"] == 0
