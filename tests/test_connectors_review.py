"""Offline-Tests für US-Konnektoren, Impressum-Parser und Review-Rückspielung."""
from openpyxl import Workbook
from agent6_engine import db, entity_resolution as er, review_apply
from agent6_engine.connectors import (SECEdgarConnector, SAMGovConnector,
                                       PatentsViewConnector, FCCIDConnector, ImpressumConnector)


def test_us_connector_parsers():
    sec = SECEdgarConnector().parse({"hits": {"hits": [
        {"_source": {"display_names": ["ASTEC INDUSTRIES INC (CIK 0000792987)"]}}]}})
    assert any(c.predicate == "cik" and c.value == "0000792987" for c in sec)

    sam = SAMGovConnector().parse({"entityData": [{"entityRegistration": {
        "ueiSAM": "ABC123DEF456", "legalBusinessName": "ACME LLC"}}]})
    assert any(c.predicate == "uei" and c.value == "ABC123DEF456" for c in sam)

    pv = PatentsViewConnector().parse({"patents": [
        {"patent_id": "1", "patent_title": "Tracked remote"},
        {"patent_id": "2", "patent_title": "CAN bus"}]})
    assert any(c.predicate == "patent_count" and c.value == "2" for c in pv)

    fcc = FCCIDConnector().parse({"results": [{"fcc_id": "ABC-123", "applicant": "X", "product": "Remote"}]})
    assert any(c.predicate == "funk_present" and c.value == "true" for c in fcc)


def test_impressum_parser():
    html = ("<html><body><h1>Impressum</h1>"
            "Geschäftsführer: Max Mustermann<br>"
            "USt-IdNr.: DE 123456789</body></html>")
    claims = ImpressumConnector().parse(html, url="https://x.de/impressum")
    preds = {c.predicate: c.value for c in claims}
    assert preds.get("vat") == "DE123456789"
    assert "Max" in (preds.get("managing_director") or "")


def test_review_apply_merge(tmp_path):
    eng = db.make_engine("sqlite:///:memory:")
    s = db.init_db(eng)()
    surv, _ = er.upsert_org(s, "Existing Co GmbH", country="DE")
    newo, _ = er.upsert_org(s, "New Co GmbH", country="DE")
    s.commit()
    assert surv.id != newo.id

    wb = Workbook(); ws = wb.active; ws.title = "Merge-Review"
    ws.append(["#", "Neuer OEM", "Möglicher Treffer", "Tier", "Score", "Grund", "Entscheidung"])
    ws.append([1, "New Co GmbH", "Existing Co GmbH", "brand", 0.5, "test", "merge"])
    p = tmp_path / "rev.xlsx"; wb.save(p)

    res = review_apply.apply_review(s, str(p))
    from sqlalchemy import select, func
    from agent6_engine.db import Organization
    assert res["merged"] == 1
    assert s.scalar(select(func.count(Organization.id))) == 1
    s.close()
