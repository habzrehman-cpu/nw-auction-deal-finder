from pathlib import Path

from tracker.db import Database
from tracker.legal import discover_legal_links, analyse_legal_documents, uploaded_document
from tracker.planning import summarise_constraints, summarise_applications
from tracker.underwriting import underwrite_property, UnderwritingDefaults


def test_planning_constraint_scoring_and_labels():
    entities = [
        {"dataset": "green-belt", "reference": "GB1", "name": "North Belt", "entity": 1},
        {"dataset": "flood-risk-zone", "reference": "ABC/3", "name": "", "entity": 2},
    ]
    items, risk = summarise_constraints(entities)
    assert len(items) == 2
    assert risk >= 4
    assert any("Green belt" in x["label"] for x in items)
    assert max(x["severity"] for x in items) == 5


def test_planning_application_subject_match_and_upside():
    apps = [{
        "reference": "24/001", "point": "POINT (-2.48 53.75)",
        "address-text": "10 Test Street Blackburn BB1 1AA",
        "description": "Conversion to three residential apartments",
        "planning-decision": "Approve", "start-date": "2025-01-01",
        "documentation-url": "https://example.test/24-001",
    }]
    items, upside = summarise_applications(apps, 53.75, -2.48, "BB1 1AA", "10 Test Street Blackburn BB1 1AA")
    assert items[0]["likely_subject"] is True
    assert upside >= 3
    assert items[0]["source_url"].startswith("https://")


def test_legal_link_discovery_classifies_pack_addendum_and_title():
    html = '''
    <a href="/lot/legal-pack">Legal Pack</a>
    <a href="/docs/addendum.pdf">Addendum</a>
    <a href="/docs/title-register.pdf">Official Copy Title Register</a>
    <a href="/photos">Photos</a>
    '''
    links = discover_legal_links(html, "https://auction.example/lot/1")
    types = {x["doc_type"] for x in links}
    assert "Legal pack" in types
    assert "Addendum" in types
    assert "Title register" in types
    assert len(links) == 3


def test_legal_analysis_extracts_core_terms_and_risks():
    text = '''
    SPECIAL CONDITIONS OF SALE. Deposit 10%. Completion shall take place 10 working days after exchange.
    VAT is payable on the purchase price and the property is opted to tax.
    Buyer shall pay the Seller's legal costs of £2,500. The title is possessory title.
    The lease has an unexpired term of 72 years. An Addendum forms part of the contract.
    '''
    docs = [{"doc_type": "Special conditions", "text_content": text}, {"doc_type": "Addendum", "text_content": "Addendum"}]
    summary = analyse_legal_documents(docs)
    assert summary["status"] == "parsed"
    assert summary["completion_days"] == 10
    assert summary["deposit_pct"] == 10
    assert summary["lease_years"] == 72
    assert summary["vat_flag"] is True
    assert summary["has_addendum"] is True
    assert summary["risk_score"] >= 7


def test_uploaded_plain_text_counts_as_material_legal_document():
    doc = uploaded_document("pack.txt", b"Special Conditions Deposit 10%. Completion 20 working days.")
    assert doc["doc_type"] == "Uploaded legal document"
    summary = analyse_legal_documents([doc])
    assert summary["status"] == "parsed"
    assert summary["parsed_document_count"] == 1


def test_db_persists_planning_and_legal_bundles(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    lot = {
        "source": "Test", "source_key": "test-1", "url": "https://example.test/1", "title": "Test",
        "address": "1 Test St BB1 1AA", "postcode": "BB1 1AA", "area": "Lancashire", "property_type": "House",
        "lot_number": "1", "guide_text": "GBP 100,000", "guide_price": 100000, "result_text": "", "result_price": None,
        "status": "Live", "auction_date": "2026-09-20", "raw_text": "Test property",
    }
    db.upsert(lot)
    row = db.property_for_key("test-1")
    db.save_planning_bundle(row["id"], {
        "provider": "Planning Data (MHCLG)", "status": "ok", "risk_score": 2.5, "opportunity_score": 3,
        "constraint_count": 1, "application_count": 1, "subject_application_count": 1,
        "warnings": ["coverage varies"], "methodology": "test", "attribution": "test",
    }, [{"kind": "constraint", "dataset": "conservation-area", "reference": "C1", "name": "CA", "severity": 2,
         "label": "Conservation area", "source_url": "https://example.test/c1", "metadata": {}}])
    db.save_legal_bundle(row["id"], {
        "provider": "Auctioneer legal pack", "status": "parsed", "risk_score": 3, "document_count": 1,
        "parsed_document_count": 1, "completion_days": 20, "deposit_pct": 10, "risk_flags": [{"severity": 2, "label": "test"}],
        "warnings": ["review"], "methodology": "test", "attribution": "test",
    }, [{"name": "Special Conditions", "url": "", "doc_type": "Special conditions", "access_status": "uploaded and parsed",
         "text_content": "Deposit 10%", "sha256": "abc", "metadata": {"origin": "user-upload"}}])
    assert db.planning_summary_for(row["id"])["risk_score"] == 2.5
    assert len(db.planning_items_for(row["id"])) == 1
    legal = db.legal_summary_for(row["id"])
    assert legal["status"] == "parsed"
    assert legal["completion_days"] == 20
    assert legal["risk_flags"][0]["label"] == "test"
    assert db.legal_documents_for(row["id"])[0]["metadata"]["origin"] == "user-upload"


def test_underwriting_stays_watch_without_legal_pack_gate():
    lot = {"property_type": "House", "guide_price": 80000, "status": "No Bids", "raw_text": "Vacant freehold house requiring refurbishment"}
    analysis = {
        "opening_offer": 65000, "failure_count": 1, "price_reduction_pct": 10, "features": {"vacant": True, "refurbishment": True},
        "tenure": "Freehold", "detail_enriched": True, "comparable_confidence": 80, "comparable_count": 6,
        "comparable_valuation_mid": 150000, "comparable_provider": "HMLR", "legal_status": "links-only",
        "planning_status": "ok", "planning_risk_score": 0, "legal_risk_score": 0,
    }
    result = underwrite_property(lot, analysis, assumptions={"gdv": 150000, "refurb_cost": 20000}, defaults=UnderwritingDefaults())
    assert result["recommendation"] == "WATCH"
    assert "legal pack" in result["recommended_action"].lower()


def test_underwriting_combines_high_legal_risk_into_pass():
    lot = {"property_type": "House", "guide_price": 80000, "status": "No Bids", "raw_text": "Vacant house"}
    analysis = {
        "opening_offer": 65000, "failure_count": 1, "features": {"vacant": True}, "tenure": "Freehold",
        "legal_status": "parsed", "legal_risk_score": 9, "legal_risk_flags": [{"severity": 5, "label": "Possessory title"}],
        "planning_status": "ok", "planning_risk_score": 1,
    }
    result = underwrite_property(lot, analysis, assumptions={"gdv": 150000, "refurb_cost": 10000}, defaults=UnderwritingDefaults())
    assert result["recommendation"] == "PASS"
    assert result["risk_score"] >= 8
