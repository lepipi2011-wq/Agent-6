"""Resume: bereits geerntete OEMs (aus sources.csv) werden übersprungen."""
import csv, os
from agent6_engine.cli import _filter_seeds
from agent6_engine.master_io import Seed


def _seeds():
    return [Seed(oem=f"OEM{i}", pattern="P4", segment=None, land="DE",
                 domain=f"https://oem{i}.de", link=None, row=i) for i in range(5)]


def _cfg(tmp, resume=True, max_oems=0):
    return {"harvest": {"countries": [], "patterns": [], "max_oems": max_oems, "resume": resume},
            "output": {"dir": str(tmp), "sources_csv": "sources.csv"}}


def _write_done(tmp, names):
    with open(os.path.join(tmp, "sources.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "cls", "oem", "pat", "url", "stype", "score", "lic", "ts"])
        for n in names:
            w.writerow(["p", "P4", n, "", "u", "oem_direct", 3, "public", "t"])


def test_resume_skips_done(tmp_path):
    _write_done(tmp_path, ["OEM0", "OEM1", "OEM2"])
    out = _filter_seeds(_seeds(), _cfg(tmp_path, resume=True))
    assert {s.oem for s in out} == {"OEM3", "OEM4"}   # 3 erledigte übersprungen


def test_fresh_ignores_done(tmp_path):
    _write_done(tmp_path, ["OEM0", "OEM1", "OEM2"])
    out = _filter_seeds(_seeds(), _cfg(tmp_path, resume=False))
    assert len(out) == 5                              # --fresh: alle wieder dabei


def test_resume_then_limit(tmp_path):
    _write_done(tmp_path, ["OEM0"])
    out = _filter_seeds(_seeds(), _cfg(tmp_path, resume=True, max_oems=2))
    assert [s.oem for s in out] == ["OEM1", "OEM2"]   # Limit gilt für die OFFENEN
