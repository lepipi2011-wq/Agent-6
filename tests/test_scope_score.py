"""Scope-Score: Verdikt-Normalisierung, Lehrbeispiele, Lern-Monitor."""
from agent6_engine.scope_score import normalize_verdikt, build_lessons, evaluate


def test_normalize_verdikt():
    assert normalize_verdikt("✓ In-Scope") == "In-Scope"
    assert normalize_verdikt("✗ Rad / Out-of-Scope") == "Out-of-Scope"
    assert normalize_verdikt("~ Unsicher") == "Unsicher"
    assert normalize_verdikt("⌀ Kein Objekt / unbrauchbar") == "Kein Objekt"
    assert normalize_verdikt("") == ""


def test_build_lessons_ausgewogen():
    rows = [
        {"oem": "Cormidi", "anwendung": "Mini-Dumper", "pattern": "P10", "verdikt": "✓ In-Scope"},
        {"oem": "AS-Motor", "anwendung": "Rad-Mäher", "pattern": "P10", "verdikt": "✗ Out-of-Scope"},
        {"oem": "XY", "anwendung": "?", "pattern": "P4", "verdikt": "~ Unsicher"},
    ]
    txt = build_lessons(rows)
    assert "Cormidi" in txt and "AS-Motor" in txt and "GELERNTE BEISPIELE" in txt


def test_evaluate_trefferquote():
    rows = [
        {"pattern": "P10", "verdikt": "In-Scope", "claude_urteil": "In-Scope"},    # Treffer
        {"pattern": "P10", "verdikt": "Out-of-Scope", "claude_urteil": "In-Scope"}, # daneben
        {"pattern": "P6", "verdikt": "In-Scope", "claude_urteil": "In-Scope"},     # Treffer
        {"pattern": "P6", "verdikt": "Kein Objekt", "claude_urteil": "Out-of-Scope"}, # Treffer (collapse)
    ]
    res = evaluate(rows)
    assert res["n"] == 4 and res["treffer"] == 3
    assert res["trefferquote"] == 0.75
    assert res["je_pattern"]["P6"]["quote"] == 1.0
    assert res["je_pattern"]["P10"]["quote"] == 0.5


def test_evaluate_ignoriert_unbewertete():
    rows = [{"verdikt": "", "claude_urteil": "In-Scope"},
            {"verdikt": "In-Scope", "claude_urteil": ""}]
    assert evaluate(rows)["n"] == 0
