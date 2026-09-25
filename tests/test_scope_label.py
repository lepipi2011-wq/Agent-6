"""Scope-Labels aus dem Master (Spalte 22) werden respektiert."""
from agent6_engine.master_io import scope_from_label, Seed
from agent6_engine.cli import _filter_seeds


def test_scope_from_label_normalisiert():
    # Ausschlüsse — auch mit Emoji/(Triage)-Varianten
    for t in ["⟶ Adjacent Market", "⟶ Adjacent Market (Triage)", "⛔ Ausschluss P3",
              "Ausschluss P3 (Sewer/Pipeline)", "⟶ Distributor — OEM gesucht (Triage)",
              "⚠️ Umfirmiert (Triage)"]:
        assert scope_from_label(t) == "exclude", t
    # Leads
    for t in ["✓ Crawler-Lead (Triage)", "✓ Crawler-Lead · Funk vorhanden", "✓ Crawler-Lead (verif.)"]:
        assert scope_from_label(t) == "lead", t
    # Offen
    for t in ["⚠ Scope/Verifikation offen", "⚠ Pipedrive-Dedup offen"]:
        assert scope_from_label(t) == "open", t
    assert scope_from_label("") == "" and scope_from_label(None) == ""


def _seed(oem, scope=""):
    return Seed(oem=oem, pattern="P4", segment=None, land="DE",
                domain="https://x.de", link=None, row=1, scope=scope)


def test_harvester_ueberspringt_ausschluesse(tmp_path):
    seeds = [_seed("Guter OEM", "lead"), _seed("Adjacent Firma", "exclude"),
             _seed("Ungelabelt", ""), _seed("Noch einer", "exclude")]
    cfg = {"harvest": {"countries": [], "patterns": [], "max_oems": 0,
                       "resume": False, "respect_scope_label": True},
           "output": {"dir": str(tmp_path), "sources_csv": "sources.csv"}}
    out = _filter_seeds(seeds, cfg)
    assert {s.oem for s in out} == {"Guter OEM", "Ungelabelt"}   # beide 'exclude' raus


def test_kann_abgeschaltet_werden(tmp_path):
    seeds = [_seed("A", "exclude"), _seed("B", "")]
    cfg = {"harvest": {"countries": [], "patterns": [], "max_oems": 0,
                       "resume": False, "respect_scope_label": False},
           "output": {"dir": str(tmp_path), "sources_csv": "sources.csv"}}
    assert len(_filter_seeds(seeds, cfg)) == 2
