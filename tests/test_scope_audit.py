"""Scope-Audit: Gruppierung nach OEM, Verdikt-Parsing, Lauf mit Fake-Auditor."""
import os
from agent6_engine import scope_audit as SA


def test_group_by_oem(tmp_path):
    for n in ["P3__Eddyfi-Technologies-CA__0.jpg", "P3__Eddyfi-Technologies-CA__1.jpg",
              "P4__Casagrande-IT__0.jpg", "not_matching.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    g = SA.group_images_by_oem(str(tmp_path))
    assert ("P3", "Eddyfi Technologies CA") in g
    assert len(g[("P3", "Eddyfi Technologies CA")]) == 2
    assert ("P4", "Casagrande IT") in g


def test_parse_audit_verdict():
    assert SA.parse_audit_verdict('{"verdict":"drop","reason":"Handscanner"}')[0] == "drop"
    assert SA.parse_audit_verdict('{"verdict":"keep","reason":"Raupe"}')[0] == "keep"
    assert SA.parse_audit_verdict("garbage")[0] == "unsure"


def test_run_audit_with_fake(tmp_path):
    for n in ["P3__Eddyfi-Technologies-CA__0.jpg", "P4__Casagrande-IT__0.jpg"]:
        (tmp_path / n).write_bytes(b"x")

    def fake(oem, cls, paths):
        return ("drop", "NDT") if "Eddyfi" in oem else ("keep", "Raupe")

    out = tmp_path / "audit.xlsx"
    res = SA.run_audit({"output": {"dir": str(tmp_path)}}, root=str(tmp_path),
                       out_xlsx=str(out), auditor=fake)
    assert res["drop"] == 1 and res["keep"] == 1 and os.path.exists(out)


def test_only_open_ueberspringt_entschiedene(tmp_path, monkeypatch):
    """only_open: OEMs mit Master-Urteil (lead/exclude) bekommen KEINEN VLM-Call."""
    for n in ["P4__Lead-Firma__0.jpg", "P4__Adjacent-Firma__0.jpg", "P4__Offene-Firma__0.jpg"]:
        (tmp_path / n).write_bytes(b"x")
    monkeypatch.setattr(SA, "load_master_scopes", lambda cfg: {
        "lead firma": "lead", "adjacent firma": "exclude", "offene firma": "open"})

    calls = []

    def fake(oem, cls, paths):
        calls.append(oem)
        return "keep", "geprüft"

    res = SA.run_audit({"output": {"dir": str(tmp_path)}}, root=str(tmp_path),
                       out_xlsx=str(tmp_path / "a.xlsx"), auditor=fake, only_open=True)
    assert calls == ["Offene Firma"]            # nur die offene wurde gefragt
    assert res["skipped_decided"] == 2          # lead + exclude übersprungen
