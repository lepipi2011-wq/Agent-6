"""Query-Repository: Laden aktiver Queries, Fallback, Performance-Rueckmeldung."""
from agent6_engine.query_repo import QueryRepo, queries_for_pattern


class FakeP:
    img_query = "tracked mini loader"
    text_query = "Raupenlader Hersteller"
    text_terms = ""
    exclude = "wheel truck"


def _repo_with(records):
    r = QueryRepo(token="x")
    r._fetch = lambda: records
    return r


def test_load_nur_aktive_und_typ():
    recs = [
        {"id": "r1", "fields": {"Query": "tracked dumper a", "Pattern": "P1", "Typ": "Bild", "Aktiv": True}},
        {"id": "r2", "fields": {"Query": "tracked dumper b", "Pattern": "P1", "Typ": "Bild", "Aktiv": False}},
        {"id": "r3", "fields": {"Query": "crawler carrier c", "Pattern": "P4", "Typ": "Text", "Aktiv": True}},
    ]
    repo = _repo_with(recs)
    bild = repo.load(typ="Bild")
    assert list(bild) == ["P1"] and len(bild["P1"]) == 1      # inaktive raus
    text = repo.load(typ="Text")
    assert list(text) == ["P4"]


def test_pattern_filter():
    recs = [{"id": "r1", "fields": {"Query": "tracked a", "Pattern": "P1", "Typ": "Bild", "Aktiv": True}},
            {"id": "r2", "fields": {"Query": "tracked b", "Pattern": "P6", "Typ": "Bild", "Aktiv": True}}]
    repo = _repo_with(recs)
    assert list(repo.load(typ="Bild", patterns=["P6"])) == ["P6"]


def test_fallback_auf_patterns_json():
    """Kein Repo-Eintrag -> patterns.json-Query wird genutzt (kein Ausfall)."""
    e = queries_for_pattern({}, "P1", FakeP(), "Bild")
    assert e and e[0]["query"] == "tracked mini loader" and e[0]["record_id"] is None
    e2 = queries_for_pattern({}, "P4", FakeP(), "Text")
    assert e2[0]["query"] == "Raupenlader Hersteller"


def test_repo_hat_vorrang():
    repo_q = {"P1": [{"query": "aus Airtable", "negativ": "", "sprache": "DE", "record_id": "r1"}]}
    e = queries_for_pattern(repo_q, "P1", FakeP(), "Bild")
    assert e[0]["query"] == "aus Airtable"


def test_report_summiert(monkeypatch):
    recs = [{"id": "r1", "fields": {"Query": "tracked a", "Pattern": "P1", "Typ": "Bild",
                                    "Aktiv": True, "Treffer gesamt": 5}}]
    repo = _repo_with(recs)
    repo._records = recs
    sent = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"records": [{"id": "r1"}]}

    import sys, types
    fake = types.ModuleType("requests")
    def patch(url, headers=None, json=None, timeout=None):
        sent["payload"] = json; return FakeResp()
    fake.patch = patch
    monkeypatch.setitem(sys.modules, "requests", fake)
    done = repo.report({"r1": (3, 10)})
    assert done == 1
    f = sent["payload"]["records"][0]["fields"]
    assert f["Neue Treffer"] == 3 and f["Treffer gesamt"] == 8 and f["Yield"] == 0.3


def test_scope_waechter_blockt_out_of_scope():
    from agent6_engine.query_repo import validate_query
    assert validate_query("tracked mini loader stand-on")[0]
    assert not validate_query("wheel loader manufacturer")[0]          # Räder
    assert not validate_query("tracked sewer pipe inspection")[0]      # Kanal
    assert not validate_query("tracked rc car toy")[0]                 # Spielzeug
    assert not validate_query("CAN bus cable datasheet")[0]            # Bauteil
    assert not validate_query("Kompaktlader Hersteller")[0]            # kein Scope-Anker


def test_negativterm_erlaubt_begriff():
    """P3 darf 'sewer' als Negativ-Term führen, ohne abgelehnt zu werden."""
    from agent6_engine.query_repo import validate_query
    ok, _ = validate_query("tracked inspection robot military crawler",
                           "underwater sewer tunnel pipe")
    assert ok


def test_load_ueberspringt_ungueltige():
    recs = [
        {"id": "r1", "fields": {"Query": "tracked mini loader", "Pattern": "P10",
                                "Typ": "Bild", "Aktiv": True}},
        {"id": "r2", "fields": {"Query": "wheel loader kaufen", "Pattern": "P10",
                                "Typ": "Bild", "Aktiv": True}},
    ]
    repo = _repo_with(recs)
    qs = repo.load(typ="Bild")
    assert len(qs.get("P10", [])) == 1                 # nur die gültige
    assert len(repo.abgelehnt) == 1 and "raeder" in repo.abgelehnt[0][2]


def test_seed_trockenlauf(tmp_path):
    import json
    pj = tmp_path / "patterns.json"
    json.dump([
        {"code": "P10", "method": "Bild", "img_query": "tracked mini loader stand-on",
         "exclude": "", "segment": "Loader"},
        {"code": "P4", "method": "Text", "text_query": "Raupenbagger crawler Hersteller",
         "exclude": "", "segment": "Kabine"},
        {"code": "P99", "method": "Bild", "img_query": "wheel loader",   # out of scope
         "exclude": "", "segment": "X"},
    ], open(pj, "w"))
    repo = QueryRepo(token="")          # nicht enabled -> Trockenlauf
    res = repo.seed_from_patterns(str(pj), dry=True)
    assert res["neu"] == 2 and res["abgelehnt"] == 1


def test_wortgrenzen_keine_fehlalarme():
    """'chip' darf 'chipper' nicht blocken (Wortgrenzen statt Teilstring)."""
    from agent6_engine.query_repo import validate_query
    assert validate_query("tracked wood chipper walk-behind pendant")[0]


def test_tunnel_nur_bei_inspektion_verboten():
    """Spritzbeton im Tunnel ist in-scope; Tunnel-INSPEKTION nicht (Kabel führt Strom)."""
    from agent6_engine.query_repo import validate_query
    assert validate_query("tracked shotcrete robot arm tunnel crawler")[0]
    assert not validate_query("tracked inspection camera tunnel crawler")[0]
