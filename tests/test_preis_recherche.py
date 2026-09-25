"""Preis-Recherche: Größenordnung mit Quelle, Kosten-Sparlogik."""
from agent6_engine import preis_recherche as P
import csv, json


class FakeSearcher:
    def search(self, q, n=10):
        return [{"title": "Cormidi C50 for sale", "snippet": "used, EUR 18.000",
                 "url": "https://mascus.com/x"}]


class FakeClient:
    class _M:
        def __init__(self, t): self.content = [type("B", (), {"type": "text", "text": t})()]
    def __init__(self, payload): self.payload = payload
    @property
    def messages(self):
        outer = self
        class M:
            def create(self, **k):
                return FakeClient._M(json.dumps(outer.payload))
        return M()


def test_recherche_belegt():
    c = FakeClient({"preis_indikation_eur": 18000, "preis_spanne": "15.000-22.000",
                    "preis_sicherheit": "belegt", "preis_quelle": "https://mascus.com/x"})
    d = P.recherche_preis("Cormidi", "C50", "Mini-Dumper", {}, searcher=FakeSearcher(), client=c)
    assert d["preis_sicherheit"] == "belegt" and d["preis_indikation_eur"] == 18000


def test_ohne_oem_leer():
    d = P.recherche_preis("", "", "", {}, searcher=FakeSearcher(), client=FakeClient({}))
    assert d["preis_sicherheit"] == "unbekannt" and d["preis_indikation_eur"] is None


def test_run_ueberspringt_ausser_scope_und_prio(tmp_path):
    cand = tmp_path / "c.csv"
    with open(cand, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["oem", "modell", "anwendung", "prioritaet"])
        w.writeheader()
        w.writerow({"oem": "Cormidi", "modell": "C50", "anwendung": "Mini-Dumper", "prioritaet": "A"})
        w.writerow({"oem": "X", "modell": "Y", "anwendung": "AUSSER SCOPE: Dosieranlage", "prioritaet": "X"})
        w.writerow({"oem": "Z", "modell": "W", "anwendung": "Lader", "prioritaet": "C"})
    c = FakeClient({"preis_indikation_eur": 18000, "preis_spanne": "15-22k",
                    "preis_sicherheit": "belegt", "preis_quelle": "u"})
    # nur Prio A -> nur 1 recherchiert (ausser-scope + C übersprungen)
    res = P.run({}, candidates_path=str(cand), out_csv=str(tmp_path / "o.csv"),
                nur_prio={"A"}, searcher=FakeSearcher(), client=c)
    assert res["recherchiert"] == 1 and res["belegt"] == 1
