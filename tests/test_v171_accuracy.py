from datetime import datetime, timezone
from pathlib import Path

from tracker.common import parse_money_range
from tracker.db import Database
from tracker.deal_engine import infer_tenure, extract_listing_facts, score_property, history_metrics
from tracker.underwriting import extract_listing_fees, underwrite_property
from tracker.intelligence import deal_readiness


CHAPEL_DETAIL = """
For Sale By Auction | 09:30, 29 July 2026 | Lot 58A
241 Chapel Street, Salford, Lancashire, M3 5EP
Guide | £65,000 - £85,000 (plus fees)
Flat 2 Bedrooms
Tenure: Leasehold. The property is held on a 99 year lease from 1st February 2003
(thus approximately 75 years unexpired).
Call the team on 020 7625 9007 for more information
The property benefits from a private balcony and allocated parking.
Energy Efficiency Rating (EPC) Current Rating C
Further Information When purchasing a flat that has a short lease, you may need to pay
an extension premium to the freeholder.
Administration Charge - Purchasers will be required to pay an administration fee of £1,800 inc VAT
london@auctionhouse.co.uk
"""


def test_chapel_tenure_is_not_poisoned_by_freeholder_wording():
    assert infer_tenure(CHAPEL_DETAIL) == "Leasehold"
    facts = extract_listing_facts(CHAPEL_DETAIL, now=datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert facts["tenure"] == "Leasehold"
    assert facts["lease_years_remaining"] == 75.0
    assert facts["lease_term_years"] == 99
    assert facts["lease_start_date"] == "2003-02-01"
    assert facts["short_lease_warning"] is True
    assert facts["epc_rating"] == "C"
    assert facts["allocated_parking"] is True
    assert facts["balcony"] is True
    assert facts["auctioneer_phone"] == "020 7625 9007"
    assert facts["auctioneer_email"] == "london@auctionhouse.co.uk"


def test_guide_range_preserves_low_and_high():
    assert parse_money_range("£65,000 - £85,000 (plus fees)") == (65000, 85000)
    assert parse_money_range("£180,000+ (plus fees)") == (180000, None)


def test_fixed_auctionhouse_admin_fee_is_detected_without_false_percentage():
    fees = extract_listing_fees({"detail_text": CHAPEL_DETAIL})
    assert fees["auction_admin_fee_fixed"] == 1800
    assert fees["buyer_premium_pct"] is None


def test_short_lease_makes_bid_ceiling_provisional_and_readiness_blocked():
    lot = {
        "property_type": "Flat", "guide_price": 65000, "guide_text": "£65,000 - £85,000",
        "status": "Available post-auction", "raw_text": "2 Bed Flat", "detail_text": CHAPEL_DETAIL,
    }
    analysis = score_property(lot, history=[{
        "captured_at": "2026-07-29T09:30:00+00:00", "guide_price": 65000,
        "status": "Unsold", "auction_date": "29/07/2026"
    }])
    analysis.update({
        "comparable_confidence": 66, "comparable_count": 12, "comparable_valuation_mid": 180000,
        "comparable_provider": "HM Land Registry PPD", "planning_status": "ok", "legal_status": "links-only",
        "detail_enriched": True, "latitude": 53.48, "longitude": -2.26,
    })
    result = underwrite_property(lot, analysis, assumptions={}, strategy="residential")
    combined = {**analysis, **result, "legal_status": "links-only", "planning_status": "ok", "latitude": 53.48, "longitude": -2.26}
    ready = deal_readiness(combined)
    assert analysis["tenure"] == "Leasehold"
    assert analysis["listing_lease_years"] == 75.0
    assert analysis["failure_count"] == 1
    assert result["detected_auction_admin_fee_fixed"] == 1800
    assert result["short_lease_signal"] is True
    assert result["max_bid_provisional"] is True
    assert result["bid_ceiling_approved"] is False
    assert result["recommendation"] == "WATCH"
    assert ready["readiness_status"] == "BID BLOCKED"
    assert any("Short lease" in x for x in ready["readiness_blockers"])


def test_db_roundtrip_preserves_guide_high_and_history_high(tmp_path: Path):
    db = Database(tmp_path / "range.db")
    lot = {
        "source": "Auction House NW", "source_key": "range1", "url": "https://example.test/lot",
        "title": "241 Chapel Street", "address": "241 Chapel Street, Salford M3 5EP", "postcode": "M3 5EP",
        "area": "Greater Manchester", "property_type": "Flat", "lot_number": "58A",
        "guide_text": "£65,000 - £85,000", "guide_price": 65000, "guide_price_high": 85000,
        "result_text": "", "result_price": None, "status": "Available post-auction", "auction_date": "29/07/2026",
        "raw_text": "2 Bed Flat", "image_url": "",
    }
    assert db.upsert(lot) is True
    row = db.property_for_key("range1")
    assert row["guide_price_high"] == 85000
    hist = db.history_for(row["id"])
    assert hist[0]["guide_price_high"] == 85000
