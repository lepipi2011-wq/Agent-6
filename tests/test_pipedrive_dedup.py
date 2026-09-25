"""Pipedrive-Dedup: prueft Firma UND Anwendung (zwei Dimensionen)."""
from agent6_engine.pipedrive_dedup import build_index, match_status, run
import csv, json


def _idx():
    return build_index([
        {"name": "Cormidi S.r.l.", "anwendung": "Mini-Dumper"},
        {"name": "Niftylift Ltd", "anwendung": "Hubarbeitsbühne"},
        {"name": "Rapid Technic AG", "anwendung": "Geräteträger"},
    ])


def test_duplikat_firma_und_anwendung():
    """Cormidi + Mini-Dumper ist schon drin -> nicht nochmal anlegen."""
    st, org, app, _ = match_status("Cormidi S.r.l.", "Mini-Dumper", "C50", _idx())
    assert st == "duplikat" and org == "Cormidi S.r.l."


def test_neue_anwendung_bei_bestandskunde():
    """Cormidi kennt das CRM — aber Spritzbeton-Roboter ist NEU -> echte Chance."""
    st, org, _app, _ = match_status("Cormidi S.r.l.", "Spritzbeton-Roboter", "SR200", _idx())
    assert st == "neue_anwendung" and org == "Cormidi S.r.l."


def test_neue_firma():
    st, _o, _a, _ = match_status("Völlig Andere Maschinen GmbH", "Mini-Dumper", "X", _idx())
    assert st == "neu"


def test_tippfehler_wird_zur_pruefung():
    """Niftylift-Fall: 'Niftilift' hat kein gemeinsames Token, wird aber gefunden."""
    st, org, _a, _ = match_status("Niftilift", "Hubarbeitsbühne", "", _idx())
    assert st == "pruefen" and "Nifty" in org


def test_whitelist_verhindert_falschtreffer():
    idx = build_index([{"name": "Rapid Technic AG", "anwendung": "Geräteträger"}])
    st, _o, _a, _ = match_status("Rapid Maschinenfabrik GmbH", "Häcksler", "", idx)
    assert st == "neu"


def test_anwendung_fuzzy():
    """Schreibvarianten der Anwendung gelten als dieselbe."""
    st, _o, _a, _ = match_status("Cormidi S.r.l.", "Minidumper", "", _idx())
    assert st == "duplikat"


def test_run_end_to_end(tmp_path):
    cand = tmp_path / "c.json"
    json.dump([
        {"oem": "Cormidi S.r.l.", "anwendung": "Mini-Dumper", "modell": "C50"},
        {"oem": "Cormidi S.r.l.", "anwendung": "Spritzbeton-Roboter", "modell": "SR200"},
        {"oem": "Neue Firma GmbH", "anwendung": "Stubbenfräse", "modell": "Z"},
    ], open(cand, "w"))
    pd = tmp_path / "pd.csv"
    with open(pd, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Deal"])
        w.writerow(["Cormidi S.r.l.", "Mini-Dumper"])
    out = tmp_path / "d.csv"
    res = run(str(cand), str(pd), str(out))
    assert res["duplikat"] == 1 and res["neue_anwendung"] == 1 and res["neu"] == 1
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert rows[1]["dedup_status"] == "neue_anwendung"


def test_load_xlsx(tmp_path):
    """Pipedrive-Export als Excel wird direkt gelesen (openpyxl)."""
    from openpyxl import Workbook
    from agent6_engine.pipedrive_dedup import load_pipedrive
    wb = Workbook(); ws = wb.active
    ws.append(["Organization", "Deal Title", "Wert"])
    ws.append(["Cormidi S.r.l.", "Mini-Dumper C50", 12000])
    ws.append(["Niftylift Ltd", "Hubarbeitsbühne", 30000])
    f = tmp_path / "pd.xlsx"; wb.save(f)
    rows = load_pipedrive(str(f))
    assert len(rows) == 2
    assert rows[0]["name"] == "Cormidi S.r.l." and "Mini-Dumper" in rows[0]["anwendung"]


def test_xlsx_mit_vorspann(tmp_path):
    """Kopfzeile wird auch gefunden, wenn Zeilen davor stehen."""
    from openpyxl import Workbook
    from agent6_engine.pipedrive_dedup import load_pipedrive
    wb = Workbook(); ws = wb.active
    ws.append(["Export vom 01.07.2026"]); ws.append([])
    ws.append(["Name", "Anwendung"])
    ws.append(["Boxer Equipment", "Mini-Loader"])
    f = tmp_path / "pd2.xlsx"; wb.save(f)
    rows = load_pipedrive(str(f))
    assert len(rows) == 1 and rows[0]["name"] == "Boxer Equipment"


def test_airtable_write(tmp_path):
    """Dedup-Status wird nach Airtable geschrieben (Fake-Writer)."""
    import json as _j, csv as _c
    cand = tmp_path / "c.json"
    _j.dump([{"oem": "Neue Firma", "anwendung": "X", "modell": "Y", "bild_url": "https://a.com/1.jpg"}],
            open(cand, "w"))
    pd = tmp_path / "pd.csv"
    with open(pd, "w", newline="", encoding="utf-8") as f:
        w = _c.writer(f); w.writerow(["Name", "Deal"]); w.writerow(["Andere GmbH", "Z"])

    class FakeAT:
        enabled = True
        def __init__(self): self.got = None
        def update_fields(self, rows, field_map, key="bild_url"):
            self.got = (rows, field_map); return len(rows)

    at = FakeAT()
    res = run(str(cand), str(pd), str(tmp_path / "d.csv"), airtable=at)
    assert res["airtable_updated"] == 1
    assert at.got[1] == {"Dedup-Status": "dedup_status", "Pipedrive-Firma": "pipedrive_firma"}
    assert at.got[0][0]["dedup_status"] == "neu"
