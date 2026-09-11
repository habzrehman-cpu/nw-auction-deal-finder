from pathlib import Path

from tracker.db import Database
from tracker.legal import analyse_legal_documents
from tracker.intelligence import build_vendor_story, buyer_leverage, deal_readiness, solicitor_questions, deal_brief_markdown


def legal_sample():
    return """
    Title number GM123456
    B: Proprietorship Register
    PROPRIETOR: NORTH STAR PROPERTY LIMITED (Company number: 01234567) of 1 Market Street, Manchester.
    Registered Charge dated 1 January 2024.
    The Lease is for a term of 99 years from 1 February 2003.
    Ground rent £250 per annum.
    Service charge £1,850 for the current year. There are no arrears stated.
    Deposit: 10% of the purchase price.
    Completion shall take place 20 working days after exchange.
    The Buyer shall reimburse the Seller's legal costs of £1,500.
    EWS1 / cladding position is to be confirmed.
    Seller's Solicitor: Example Legal LLP
    Email: auctions@examplelegal.co.uk
    Telephone: 0161 555 1212
    """


def test_structured_legal_pack_extracts_owner_lease_and_contacts():
    docs = [{
        "name": "Official Copy Register.pdf", "doc_type": "Title register",
        "text_content": legal_sample(), "access_status": "uploaded and parsed"
    }]
    result = analyse_legal_documents(docs)
    fields = result["extracted_fields"]
    assert result["status"] == "parsed"
    assert fields["title_number"] == "GM123456"
    assert fields["proprietor_name"] == "NORTH STAR PROPERTY LIMITED"
    assert fields["company_number"] == "01234567"
    assert 74 <= fields["lease_years_remaining"] <= 76
    assert fields["ground_rent_amount"] == 250
    assert fields["service_charge_amount"] == 1850
    assert fields["seller_costs_amount"] == 1500
    assert fields["ews1_or_cladding_flag"] is True
    assert result["completion_days"] == 20
    assert result["deposit_pct"] == 10
    assert any(c.get("email") == "auctions@examplelegal.co.uk" for c in result["contacts"])
    assert any("fewer than 80 years" in f["label"] for f in result["risk_flags"])


def test_legal_summary_roundtrip_persists_structured_fields(tmp_path):
    db = Database(tmp_path / "tracker.db")
    # Create a minimal property row so FK references are meaningful.
    db.upsert({
        "source": "Test", "source_key": "x1", "url": "https://example.test/1", "title": "1 Test Road",
        "address": "1 Test Road", "postcode": "M1 1AA", "area": "Greater Manchester",
        "property_type": "Flat", "lot_number": "1", "guide_text": "£100,000", "guide_price": 100000,
        "result_text": "", "result_price": None, "status": "Live", "auction_date": "2026-09-30", "raw_text": ""
    })
    row = db.property_for_key("x1")
    docs = [{"name": "register.pdf", "doc_type": "Title register", "text_content": legal_sample(), "access_status": "uploaded and parsed"}]
    summary = analyse_legal_documents(docs)
    db.save_legal_bundle(row["id"], summary, docs)
    saved = db.legal_summary_for(row["id"])
    assert saved["extracted_fields"]["title_number"] == "GM123456"
    assert saved["extracted_fields"]["company_number"] == "01234567"
    assert saved["contacts"][0]["role"] in {"Seller solicitor", "Solicitor"}


def test_vendor_story_separates_fact_from_inference():
    lot = {"status": "Available post-auction", "title": "Vacant property", "raw_text": "vacant possession", "detail_text": ""}
    deal = {"failure_count": 2, "price_reduction_pct": 12.5, "days_since_failure": 30, "features": {"vacant": True}}
    history = [
        {"auction_date": "2026-06-01", "status": "Unsold", "guide_price": 170000, "guide_text": "£170,000"},
        {"auction_date": "2026-08-01", "status": "Unsold", "guide_price": 150000, "guide_text": "£150,000"},
    ]
    planning = [{
        "kind": "application", "likely_subject": 1, "reference": "A/1", "label": "Change of use",
        "source_url": "https://planning.test/A1", "metadata": {"planning-decision": "Refused", "decision-date": "2026-03-01", "description": "Change of use to HMO"}
    }]
    story = build_vendor_story(lot, history, deal, {}, planning)
    assert story["buyer_leverage_score"] >= 8
    assert any("2 distinct failed-auction" in x for x in story["confirmed_facts"])
    assert any("suggests" in x.lower() or "may" in x.lower() for x in story["inferences"])
    assert len(story["timeline"]) == 3


def test_readiness_blocks_missing_legal_and_works():
    row = {
        "status": "Available post-auction", "detail_enriched": True, "history_points": 2,
        "failure_count": 1, "comparable_confidence": 72, "market_value": 200000,
        "planning_status": "ok", "legal_status": "links-only", "works_missing": True,
        "tenure": "Leasehold", "legal_lease_years": 75, "latitude": 53.5, "longitude": -2.2,
        "nearest_junction": "M60 J1",
    }
    result = deal_readiness(row)
    assert result["readiness_pct"] < 85
    assert any("Legal pack" in x for x in result["readiness_blockers"])
    assert any("Works estimate" in x for x in result["readiness_blockers"])
    assert any("Short lease" in x for x in result["readiness_blockers"])


def test_workspace_and_notes_roundtrip(tmp_path):
    db = Database(tmp_path / "tracker.db")
    db.upsert({
        "source": "Test", "source_key": "deal1", "title": "Deal", "address": "Deal", "postcode": "BB1 1AA",
        "area": "Lancashire", "property_type": "Commercial", "status": "Live", "guide_price": 200000,
        "guide_text": "£200,000", "auction_date": "2026-10-01", "raw_text": ""
    })
    pid = db.property_for_key("deal1")["id"]
    db.save_workspace(pid, "Auctioneer Contacted", "Call back with offer", "2026-09-15")
    db.add_note(pid, "Agent says vendor wants certainty of completion.")
    ws = db.workspace_for(pid)
    assert ws["stage"] == "Auctioneer Contacted"
    assert ws["follow_up_date"] == "2026-09-15"
    assert db.notes_for(pid)[0]["note"].startswith("Agent says")


def test_solicitor_questions_cover_short_lease_and_ews1():
    row = {"tenure": "Leasehold", "legal_lease_years": 75, "legal_vat_flag": False}
    legal = {"status": "parsed", "completion_days": 20, "extracted_fields": {
        "lease_years_remaining": 75, "ews1_or_cladding_flag": True, "service_charge_amount": 1800
    }}
    qs = solicitor_questions(row, legal)
    assert any("lease" in q.lower() and "75" in q for q in qs)
    assert any("ews1" in q.lower() for q in qs)
    assert any("service charge" in q.lower() for q in qs)


def test_deal_brief_contains_decision_and_seller_story():
    row = {"address": "1 Deal Road", "source": "Auction House", "status": "Available post-auction",
           "guide_price": 100000, "browse_score": 8.0, "motivation_score": 8.5, "opening_offer": 85000,
           "max_bid": 110000, "market_value": 150000, "recommendation": "WATCH", "recommended_action": "Review legal pack"}
    story = {"buyer_leverage_score": 8.2, "seller_profile": {"seller_name": "ABC LTD", "seller_type": "Receiver", "title_number": "GM1"},
             "confirmed_facts": ["Failed once"], "inferences": ["Seller may value certainty"]}
    readiness = {"readiness_pct": 65, "readiness_status": "IN PROGRESS", "readiness_blockers": ["Legal pack not parsed"]}
    brief = deal_brief_markdown(row, story, readiness, [{"action": "Get legal pack", "reason": "Required"}])
    assert "ABC LTD" in brief
    assert "Buyer leverage: 8.2/10" in brief
    assert "WATCH" in brief
    assert "Legal pack not parsed" in brief
