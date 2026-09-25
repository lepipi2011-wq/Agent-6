"""HMI-Anreicherung v2: Dealer-Erkennung, Seiten-Dedup, OEM-Nachladen, OEM+Modell-Dedup."""
from agent6_engine import hmi_enrichment as H
import json, csv


def test_is_dealer():
    assert H.is_dealer("https://www.masterwholesale.com/x")
    assert H.is_dealer("https://houseofcontractors.com/y")
    assert not H.is_dealer("https://www.cormidi.com/z")


def test_page_dedup_and_oem_dedup(tmp_path):
    # 3x dieselbe Ensign-Seite + 1x Imer -> Seiten-Dedup auf 2
    manifest = tmp_path / "m.json"
    json.dump([
        {"url": "a1.jpg", "pattern": "P1", "page": "https://ensigneq.com/x"},
        {"url": "a2.jpg", "pattern": "P1", "page": "https://ensigneq.com/x"},
        {"url": "a3.jpg", "pattern": "P1", "page": "https://ensigneq.com/x"},
        {"url": "b1.jpg", "pattern": "P1", "page": "https://imer.it/carry"},
    ], open(manifest, "w"))

    def fake_fetch(url): return "text"

    def fake_enrich(text, url, pat):
        if "ensign" in "" or True:  # entscheiden über page nicht möglich hier -> per url? nutze fetcher-Ergebnis
            pass
        return {}

    calls = {"n": 0}

    def enr(text, url, pat):
        calls["n"] += 1
        return {"oem": "Ensign", "modell": "Dumper", "anwendung": "Kipper",
                "hmi_typ": "Stationär/fest", "sprache": "en", "reason": "Bedienpult"}

    res = H.run({}, manifest_path=str(manifest), out_csv=str(tmp_path / "e.csv"),
                fetcher=fake_fetch, enricher=enr, resolver=lambda o, m: None)
    assert res["input"] == 4 and res["nach_seiten_dedup"] == 2   # Seiten-Dedup
    assert calls["n"] == 2                                       # nur 2x angereichert (Kostenersparnis)
    assert res["stationaer"] == 1                                # Stationär/fest erkannt
    assert res["final"] == 1                                     # OEM+Modell-Dedup (beide "Ensign/Dumper")


def test_oem_nachladen_bei_haendler(tmp_path):
    manifest = tmp_path / "m.json"
    json.dump([{"url": "i.jpg", "pattern": "P1", "page": "https://masterwholesale.com/imer"}], open(manifest, "w"))

    def fake_fetch(url): return "text"

    def enr(text, url, pat):
        # erste (Händler) unklar, nach Nachladen Kabel
        return {"oem": "Imer", "modell": "Carry107", "anwendung": "Mini-Dumper",
                "hmi_typ": "Stationär/fest" if "resolved" in url else "unklar",
                "sprache": "en", "reason": "x"}

    # resolver liefert eine OEM-URL; fetch gibt für sie "resolved" zurück
    def fetch2(url): return "resolved" if "imergroup" in url else "text"
    def resolver(oem, modell): return "https://imergroup.com/carry107"

    res = H.run({}, manifest_path=str(manifest), out_csv=str(tmp_path / "e.csv"),
                fetcher=fetch2, enricher=lambda t, u, p: enr(t, "resolved" if "resolved" in t else "", p),
                resolver=resolver)
    assert res["oem_nachgeladen"] == 1 and res["stationaer"] == 1


def test_is_aggregator():
    assert H.is_aggregator("https://www.machinerytrader.com/listings/x")
    assert H.is_aggregator("https://media.sandhills.com/img.axd?id=1")
    assert not H.is_aggregator("https://www.banditchippers.com/sg75")


def test_aggregator_seite_wird_aufgeloest(tmp_path):
    """Aggregator-Listing (machinerytrader, Bild von sandhills-CDN): tote Seite NICHT
    fetchen, sondern per Titel die OEM-Seite aufloesen und DIESE anreichern — auch wenn
    hmi_typ 'unklar' bleibt. Frueher fiel so ein Record als AUSSER SCOPE raus."""
    import json, csv
    mf = tmp_path / "m.json"
    json.dump([{"url": "https://media.sandhills.com/img.axd?id=1", "pattern": "P8",
                "page": "https://www.machinerytrader.com/listings/2019-bandit-sg75",
                "title": "2019 Bandit SG-75 Track Stump Grinder"}], open(mf, "w"))
    fetched = []

    def fetch(url):
        fetched.append(url)
        return "resolved-oem-text" if "banditchippers" in url else "LEER"

    def enr(t, u, p):
        if t == "resolved-oem-text":
            return {"ist_zielmaschine": True, "oem": "Bandit Industries", "modell": "SG-75 Track",
                    "anwendung": "Stubbenfräse", "hmi_typ": "unklar", "can_bus": "unklar",
                    "can_reason": "", "preis_eur": None, "preis_beleg": "", "sprache": "en", "reason": "x"}
        return {"ist_zielmaschine": False, "oem": "", "modell": "", "anwendung": "",
                "hmi_typ": "unklar", "can_bus": "unklar", "preis_eur": None, "sprache": "", "reason": "leer"}

    def resolver(oem, modell, seed=""):
        return "https://banditchippers.com/sg75" if "Bandit" in (seed or "") else None

    res = H.run({}, manifest_path=str(mf), out_csv=str(tmp_path / "e.csv"),
                fetcher=fetch, enricher=enr, resolver=resolver)
    assert res["via_aggregator"] == 1 and res["oem_nachgeladen"] == 1
    assert not any("machinerytrader" in u for u in fetched)   # tote Seite NICHT gefetcht
    row = list(csv.DictReader(open(tmp_path / "e.csv", encoding="utf-8")))[0]
    assert row["oem"] == "Bandit Industries" and row["prioritaet"] != "X"


def test_no_key(monkeypatch):
    # Deterministisch: KEINEN Client erzwingen, egal ob ANTHROPIC_API_KEY in der Umgebung
    # liegt. Sonst faellt enrich() ueber _client() auf einen echten Client zurueck und
    # ruft Claude real -> reason != "kein-key" (Test-Isolation, kein Pipeline-Bug).
    monkeypatch.setattr(H, "_client", lambda: None)
    d = H.enrich("t", "u", "P1", {}, client=None)
    assert d["hmi_typ"] == "unklar" and d["reason"] == "kein-key"


def test_run_akzeptiert_kandidatenliste(tmp_path):
    """--from-airtable uebergibt eine Liste statt eines Manifest-Pfads."""
    cands = [{"url": "https://x.com/a.jpg", "pattern": "P10", "page": "https://x.com/p"}]

    def enr(t, u, p):
        return {"oem": "X", "modell": "M", "anwendung": "Mini-Dumper",
                "hmi_typ": "Funk", "can_bus": "unklar", "can_reason": "",
                "preis_eur": None, "preis_beleg": "", "sprache": "de", "reason": "r"}

    res = H.run({}, manifest_path=cands, out_csv=str(tmp_path / "e.csv"),
                fetcher=lambda u: "t", enricher=enr, resolver=lambda o, m: None)
    assert res["input"] == 1 and res["enriched"] == 1


def test_candidates_missing_filtert_und_faellt_auf_domain_zurueck():
    """Records ohne HMI-Typ werden geladen; fehlende Quell-Seite -> Domain-Wurzel."""
    from agent6_engine.image_search_harvester import AirtableWriter
    w = AirtableWriter(token="x")
    w._all_records = lambda: [
        {"id": "1", "fields": {"Bild-URL": "https://a.com/x/img.jpg",
                               "Pattern-Vorschlag": "P10 Stand-On Mini Loader"}},
        {"id": "2", "fields": {"Bild-URL": "https://b.com/y.jpg", "HMI-Typ": "Funk"}},
        {"id": "3", "fields": {"Bild-URL": "https://c.com/z.jpg",
                               "Quell-Seite": "https://c.com/produkt"}},
    ]
    out = w.candidates_missing("HMI-Typ")
    assert len(out) == 2                                  # Record 2 hat schon HMI-Typ
    assert out[0]["page"] == "https://a.com"              # Fallback Domain-Wurzel
    assert out[0]["pattern"] == "P10"
    assert out[1]["page"] == "https://c.com/produkt"      # echte Quell-Seite


def test_out_of_scope_erzwingt_prio_x():
    # Claude-Urteil 'Out-of-Scope' -> immer Prio X, auch wenn CAN/Preis technisch passen wuerden.
    assert H.priorisiere("CAN belegt", 50000, "Funk", True, "Out-of-Scope") == "X"
    assert H.priorisiere("CAN belegt", 50000, "Funk", True, "In-Scope") == "A"
    assert H.priorisiere("CAN belegt", 50000, "Funk", True) == "A"   # rueckwaertskompatibel


def test_groesse_status_schwellen():
    assert H.groesse_status(1.5, None) == "ok"          # Gewicht erreicht Schwelle
    assert H.groesse_status(None, 20) == "ok"           # Leistung erreicht Schwelle
    assert H.groesse_status(0.3, 5) == "zu klein"       # beide bekannt, beide darunter
    assert H.groesse_status(0.3, None) == "unklar"      # Leistung unbekannt -> nicht disqualifizieren
    assert H.groesse_status(None, None) == "unklar"
    assert H.groesse_status("0,5 t", None) == "unklar"  # _num parst Komma/Einheit


def test_groesse_gate_erzwingt_prio_x():
    # Technisch A (CAN + Preis), aber zu klein -> X
    assert H.priorisiere("CAN belegt", 50000, "Funk", True, "In-Scope", "zu klein") == "X"
    assert H.priorisiere("CAN belegt", 50000, "Funk", True, "In-Scope", "ok") == "A"
    assert H.priorisiere("CAN belegt", 50000, "Funk", True, "In-Scope", "unklar") == "A"  # unklar disqualifiziert nicht


def test_candidates_reenrich_nur_unsicher():
    """--reenrich-unsicher zieht Records mit Claude-Urteil 'Unsicher' — auch wenn HMI-Typ
    schon gesetzt ist. In-Scope/Out-of-Scope werden NICHT erneut angefasst."""
    from agent6_engine.image_search_harvester import AirtableWriter
    w = AirtableWriter(token="x")
    w._all_records = lambda: [
        {"id": "1", "fields": {"Bild-URL": "https://seppi.com/a.jpg", "HMI-Typ": "unklar",
                               "Claude-Urteil": "Unsicher", "Quell-Seite": "https://seppi.com/h5-rc",
                               "Notizen": "Bildtitel: Seppi H5 RC"}},
        {"id": "2", "fields": {"Bild-URL": "https://toro.com/b.jpg", "HMI-Typ": "Stationär/fest",
                               "Claude-Urteil": "In-Scope"}},                 # fertig -> nicht anfassen
        {"id": "3", "fields": {"Bild-URL": "https://x.com/c.jpg", "HMI-Typ": "unklar",
                               "Claude-Urteil": "Out-of-Scope"}},             # verworfen -> nicht anfassen
    ]
    out = w.candidates_reenrich("Unsicher")
    assert len(out) == 1
    assert out[0]["page"] == "https://seppi.com/h5-rc"
    assert out[0]["title"] == "Seppi H5 RC"


def test_candidates_all_nimmt_alles_mit_bild_url():
    """--reenrich-all: jeder Record mit Bild-URL, unabhaengig vom Anreicherungsstand."""
    from agent6_engine.image_search_harvester import AirtableWriter
    w = AirtableWriter(token="x")
    w._all_records = lambda: [
        {"id": "1", "fields": {"Bild-URL": "https://a.com/1.jpg", "HMI-Typ": "Funk",
                               "Claude-Urteil": "In-Scope", "Quell-Seite": "https://a.com/p"}},
        {"id": "2", "fields": {"Bild-URL": "https://b.com/2.jpg"}},           # gar nicht angereichert
        {"id": "3", "fields": {"Notizen": "kein Bild"}},                       # ohne Bild-URL -> raus
    ]
    out = w.candidates_all()
    assert len(out) == 2
    assert {o["url"] for o in out} == {"https://a.com/1.jpg", "https://b.com/2.jpg"}


def test_scope_out_wird_markiert(tmp_path):
    """Nicht-Raupenmaschine (Dosieranlage) -> AUSSER SCOPE, Priorität X."""
    import json, csv
    mf = tmp_path / "m.json"
    json.dump([{"url": "a.jpg", "pattern": "P10", "page": "https://movacolor.com"}], open(mf, "w"))

    def enr(t, u, p):
        return {"ist_zielmaschine": False, "oem": "Movacolor", "modell": "MBS",
                "anwendung": "Dosieranlage", "hmi_typ": "unklar", "can_bus": "unklar",
                "can_reason": "", "preis_eur": None, "preis_beleg": "", "sprache": "de", "reason": "x"}

    res = H.run({}, manifest_path=str(mf), out_csv=str(tmp_path / "e.csv"),
                fetcher=lambda u: "t", enricher=enr, resolver=lambda o, m: None)
    assert res["ausser_scope"] == 1
    row = list(csv.DictReader(open(tmp_path / "e.csv", encoding="utf-8")))[0]
    assert row["prioritaet"] == "X" and "AUSSER SCOPE" in row["anwendung"]


def test_junk_cdn_urls():
    from agent6_engine.image_search_harvester import is_junk
    assert is_junk("https://i.ytimg.com/vi/x/hqdefault.jpg")
    assert is_junk("https://lh3.ggpht.com/y")
    assert not is_junk("https://www.ensigneq.com/dumper.jpg")


# --- Bild-Heuristik Betriebsschnittstelle (Pierre-Regel, 2026-09-24) ---
# Lockt die Regel: CAN/Spez NICHT aus dem Bild; Bild liefert Betriebsschnittstelle.
# Keine Kabine/Plattform/Sitz/Deichsel -> autonom-oder-RC (Out); sonst bediener-praesent (In).
def test_operator_interface_keine_schnittstelle_ist_out():
    assert H.operator_interface_scope() == "autonom-oder-RC"
    assert H.operator_interface_scope(False, False, False, False) == "autonom-oder-RC"

def test_operator_interface_jede_einzelne_schnittstelle_ist_in():
    assert H.operator_interface_scope(kabine=True) == "bediener-praesent"
    assert H.operator_interface_scope(plattform=True) == "bediener-praesent"   # stand-on pedana
    assert H.operator_interface_scope(sitz=True) == "bediener-praesent"
    assert H.operator_interface_scope(deichsel=True) == "bediener-praesent"    # walk-behind


# --- Urteils-Kalibrierung: Few-Shot + Anti-Ueberablehnung im Prompt vorhanden ---
def test_few_shot_urteil_konstante_vorhanden():
    fs = H.FEW_SHOT_URTEIL
    assert "In-Scope" in fs and "Out-of-Scope" in fs and "Unsicher" in fs
    # Kernregeln muessen in den Beispielen stehen:
    assert "Aktuator" in fs                       # No-Can-Regel
    assert "Verdraengung" in fs or "schon RC" in fs
    assert "autonom" in fs.lower()

def test_enrich_ohne_key_bleibt_robust():
    # ohne Client kein Absturz, definierte Defaults
    d = H.enrich("irgendein text", "http://x/y.jpg", "P4", {"harvest": {}}, client=None)
    assert d["hmi_typ"] == "unklar" and d["can_bus"] == "unklar"
