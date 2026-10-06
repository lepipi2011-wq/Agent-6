from agent6_engine.image_search_harvester import norm_url
from agent6_engine import hmi_enrichment as H

# --- A: URL-Normalisierung ---
def test_norm_url_varianten_gleich():
    a = norm_url("https://www.example.com/img/machine.jpg?w=300&v=2")
    b = norm_url("http://example.com/img/machine.jpg")
    c = norm_url("https://example.com/img/machine.jpg/")
    assert a == b == c

def test_norm_url_cdn_groessensuffix():
    assert norm_url("https://cdn.x.com/foto-300x200.jpg") == norm_url("https://cdn.x.com/foto.jpg")
    assert norm_url("https://cdn.x.com/foto_thumb.png") == norm_url("https://cdn.x.com/foto.png")

# --- C: Entitäts-Dedup ---
def test_norm_oem_rechtsform_und_land():
    assert H.norm_oem("Colmac Italia") == H.norm_oem("Colmac") == "colmac"
    assert H.norm_oem("FAE Group S.p.A.") == "fae"

def test_dedup_key_namensvarianten_mergen():
    assert H.dedup_key("PeK Agroline", "Slopehelper") == H.dedup_key("PeK Automotive", "Slopehelper")
    assert H.dedup_key("FAE", "RCU-55") == H.dedup_key("FAE Group", "rcu 55")

def test_mark_duplicates_behaelt_besten():
    rows = [
        {"oem": "Colmac", "modell": "Airone 180 ZT", "hmi_typ": "unklar", "can_bus": "unklar", "claude_konfidenz": 0.2},
        {"oem": "Colmac Italia", "modell": "airone 180 zt", "hmi_typ": "Funk", "can_bus": "CAN belegt", "claude_konfidenz": 0.9},
        {"oem": "", "modell": "", "hmi_typ": "unklar"},  # nicht deduplizierbar
    ]
    n = H.mark_duplicates(rows)
    assert n == 1
    # der bestgefuellte (Funk/CAN) bleibt Original
    winner = [r for r in rows if r.get("oem", "").lower().startswith("colmac") and r["intern_duplikat"] == ""]
    assert winner and winner[0]["can_bus"] == "CAN belegt"
    assert rows[2]["intern_duplikat"] == ""   # leerer OEM bleibt unmarkiert
