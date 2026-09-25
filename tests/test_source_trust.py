"""Quellen-Trust: cheap content (Marktplatz/Social/CDN) wird geblockt, OEM/Fachquellen nicht."""
from agent6_engine import source_trust as ST
from agent6_engine import image_search_harvester as H


def test_marktplatz_und_social_geblockt():
    for u in ("https://www.alibaba.com/x", "https://www.made-in-china.com/y",
              "https://www.tiktok.com/@a/video/1", "https://de.aliexpress.com/z",
              "https://www.machinerytrader.com/listings/1", "https://media.sandhills.com/img.axd"):
        assert ST.is_low_trust(u), u
        assert H.is_junk(u), u                     # Harvester nutzt denselben Filter


def test_oem_und_fachquelle_nicht_geblockt():
    for u in ("https://www.banditchippers.com/sg75", "https://www.liebherr.com/x",
              "https://www.hinowa.com/tracked", "https://www.forconstructionpros.com/a"):
        assert not ST.is_low_trust(u), u
        assert not H.is_junk(u), u


def test_block_reason_kategorien():
    assert ST.block_reason("https://www.tiktok.com/x") == "social/stock"
    assert ST.block_reason("https://www.machinerytrader.com/x") == "marktplatz"
    assert ST.block_reason("https://media.sandhills.com/img.axd") in ("marktplatz", "cdn/thumbnail")
    assert ST.block_reason("not a url") == "keine-domain"
    assert ST.block_reason("https://www.banditchippers.com/x") == "ok"


def test_source_score_stufen():
    assert ST.source_score("https://www.alibaba.com/x") == 1        # cheap
    assert ST.source_score("https://www.banditchippers.com/x") == 3  # OEM-Allowlist
    assert ST.source_score("https://www.some-unknown-oem.de/x") == 2  # unbekannt, nicht geblockt
