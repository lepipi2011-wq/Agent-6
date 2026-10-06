import json, datetime
from agent6_engine import run_tracking as RT

def test_new_run_id_format():
    rid = RT.new_run_id(datetime.datetime(2026, 9, 28, 14, 30))
    assert rid == "20260928-1430-" + RT.REGEL_VERSION

def test_snapshot_review_schreibt_datei(tmp_path):
    recs = [{"id": "rec1", "fields": {"Verdikt": "In-Scope"}}]
    p = RT.snapshot_review(recs, "run-x", out_dir=str(tmp_path), suffix="before")
    d = json.load(open(p, encoding="utf-8"))
    assert d["count"] == 1 and d["run_id"] == "run-x" and d["records"] == recs

def test_run_summary_keys():
    s = RT.run_summary("run-x", 42, query_set="P4,P5",
                       metrics={"recall": 0.5, "precision": 0.4}, commit="abc123", notiz="test")
    assert s["Run-ID"] == "run-x" and s["Records"] == 42 and s["Commit"] == "abc123"
    assert s["Recall"] == 0.5 and RT.REGEL_VERSION in s["Regel-Version"]

def test_write_run_log(tmp_path):
    s = RT.run_summary("run-y", 3, commit="")
    p = RT.write_run_log(s, out_dir=str(tmp_path))
    assert json.load(open(p, encoding="utf-8"))["Run-ID"] == "run-y"

def test_stamp_run_delegiert_an_update_fields(monkeypatch):
    from agent6_engine.image_search_harvester import AirtableWriter
    w = AirtableWriter(token="x")
    captured = {}
    def fake_update_fields(rows, field_map, key="bild_url"):
        captured["rows"] = rows; captured["map"] = field_map; return len(rows)
    monkeypatch.setattr(w, "update_fields", fake_update_fields)
    n = w.stamp_run([{"bild_url": "u1"}], "run-z", "v3.2")
    assert n == 1
    assert captured["map"] == {"Run-ID": "__run", "Regel-Version": "__regel"}
    assert captured["rows"][0]["__run"] == "run-z" and captured["rows"][0]["__regel"] == "v3.2"
