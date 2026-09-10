from datetime import datetime, timezone

from tracker.db import Database
from tracker.underwriting import (
    UnderwritingDefaults,
    sdlt_nonresidential,
    sdlt_residential,
    vendor_motivation,
    underwrite_property,
)


def test_current_sdlt_examples():
    assert sdlt_nonresidential(275_000) == 3_250
    assert sdlt_residential(295_000, "Standard residential") == 4_750
    assert sdlt_residential(300_000, "Additional dwelling") == 20_000
    assert sdlt_residential(600_000, "Corporate 17% > GBP500k") == 102_000


def test_vendor_motivation_repeated_failure_and_reduction_is_high():
    lot = {
        "status": "Available post-auction",
        "raw_text": "Vacant freehold property by order of a receiver",
    }
    deal = {"failure_count": 2, "price_reduction_pct": 15, "days_since_failure": 20}
    result = vendor_motivation(lot, deal)
    assert result["motivation_score"] >= 8.5
    assert result["motivation_label"] == "Very High"


def test_residential_underwriting_solves_max_bid():
    lot = {
        "status": "No Bids", "property_type": "House", "guide_price": 100_000,
        "raw_text": "Vacant freehold house requiring modernisation",
    }
    deal = {
        "opening_offer": 82_000, "failure_count": 1, "price_reduction_pct": 10,
        "days_since_failure": 4, "features": {"vacant": True, "refurbishment": True, "development": False},
        "tenure": "Freehold", "detail_enriched": True,
    }
    result = underwrite_property(
        lot, deal,
        assumptions={
            "strategy": "residential", "gdv": 165_000, "refurb_cost": 25_000,
            "contingency_pct": 10, "purchase_price": 82_000,
            "residential_sdlt_mode": "Additional dwelling", "finance_mode": "Cash",
            "target_profit_margin_pct": 20,
        },
        defaults=UnderwritingDefaults(), strategy="auto",
    )
    assert result["max_bid"] is not None
    assert result["max_bid"] < 110_000
    assert result["market_value"] == 165_000
    assert result["all_in_cost"] > 82_000
    assert result["recommendation"] in {"PURSUE", "WATCH"}


def test_commercial_underwriting_uses_psf_and_income_conservatively():
    lot = {
        "status": "Available post-auction", "property_type": "Industrial", "guide_price": 450_000,
        "raw_text": "Vacant freehold warehouse with yard loading parking",
    }
    deal = {
        "opening_offer": 380_000, "failure_count": 2, "price_reduction_pct": 12,
        "days_since_failure": 18, "size_sqft": 10_000, "price_per_sqft": 45,
        "features": {"parking": True, "loading": True, "split_potential": True, "vacant": True},
        "tenure": "Freehold", "motorway_distance_miles": 3.0, "detail_enriched": True,
    }
    result = underwrite_property(
        lot, deal,
        assumptions={
            "strategy": "commercial", "market_psf": 70, "erv_annual": 70_000,
            "exit_yield_pct": 9, "capex_cost": 20_000, "purchase_price": 380_000,
            "finance_mode": "Cash", "target_equity_margin_pct": 20,
        },
        defaults=UnderwritingDefaults(), strategy="auto",
    )
    assert result["psf_market_value"] == 700_000
    assert round(result["income_market_value"]) == 777_778
    assert result["market_value"] == 700_000
    assert result["max_bid"] is not None
    assert result["motivation_score"] >= 8
    assert result["overall_opportunity_score"] >= 6


def test_underwriting_stays_watch_without_valuation():
    lot = {"status": "Live", "property_type": "House", "guide_price": 90_000, "raw_text": "freehold house"}
    deal = {"opening_offer": 81_000, "failure_count": 0, "features": {}, "tenure": "Freehold"}
    result = underwrite_property(lot, deal, assumptions={"strategy": "residential"}, strategy="auto")
    assert result["recommendation"] == "WATCH"
    assert result["max_bid"] is None


def test_underwriting_persistence(tmp_path):
    db = Database(tmp_path / "test.db")
    db.upsert({
        "source": "Test", "source_key": "test-1", "url": "https://example.com/1", "title": "Test lot",
        "address": "Blackburn BB1 1AA", "postcode": "BB1 1AA", "area": "Lancashire", "property_type": "House",
        "lot_number": "1", "guide_text": "GBP 100,000", "guide_price": 100_000, "result_text": None,
        "result_price": None, "status": "Live", "auction_date": "2026-09-30", "raw_text": "freehold house",
    })
    row = db.property_for_key("test-1")
    db.save_underwriting(row["id"], {"strategy": "residential", "gdv": 160_000, "refurb_cost": 20_000, "underwriting_notes": "Agent call"})
    saved = db.underwriting_for(row["id"])
    assert saved["gdv"] == 160_000
    assert saved["refurb_cost"] == 20_000
    assert saved["underwriting_notes"] == "Agent call"
    assert db.underwriting_map()[row["id"]]["strategy"] == "residential"


def test_commercial_vat_affects_sdlt_even_when_vat_recoverable():
    lot = {"status": "Live", "property_type": "Commercial", "guide_price": 300_000, "raw_text": "commercial property"}
    deal = {"opening_offer": 300_000, "failure_count": 0, "features": {}, "tenure": "Freehold", "size_sqft": 5000}
    result = underwrite_property(
        lot, deal,
        assumptions={
            "strategy": "commercial", "manual_market_value": 450_000, "purchase_price": 300_000,
            "purchase_vat_pct": 20, "vat_recoverable": True, "finance_mode": "Cash",
            "auction_admin_fee": 0, "legal_cost": 0, "survey_cost": 0, "contingency_pct": 0,
        },
        strategy="auto",
    )
    assert result["purchase_vat"] == 60_000
    assert result["vat_cash_cost"] == 0
    assert result["sdlt_consideration"] == 360_000
    assert result["sdlt"] == 7_500


def test_residential_exit_and_holding_costs_are_included():
    lot = {"status": "Live", "property_type": "House", "guide_price": 80_000, "raw_text": "house"}
    deal = {"opening_offer": 75_000, "failure_count": 0, "features": {}, "tenure": "Freehold"}
    result = underwrite_property(
        lot, deal,
        assumptions={
            "strategy": "residential", "gdv": 150_000, "purchase_price": 75_000,
            "refurb_cost": 20_000, "contingency_pct": 0, "holding_cost_monthly": 300,
            "term_months": 6, "sale_cost_pct": 1.5, "exit_legal_cost": 1_500,
            "finance_mode": "Cash", "residential_sdlt_mode": "Additional dwelling",
        },
        strategy="auto",
    )
    assert result["holding_cost"] == 1_800
    assert result["sale_cost"] == 2_250
    assert result["exit_legal_cost"] == 1_500
    assert result["all_in_cost"] > 100_000


def test_residential_auto_comparables_seed_gdv_when_confident():
    lot = {"property_type": "House", "guide_price": 90000, "status": "No Bids", "raw_text": "vacant terraced house requiring modernisation"}
    analysis = {
        "opening_offer": 75000, "features": {"vacant": True, "refurbishment": True}, "tenure": "Freehold",
        "failure_count": 1, "detail_enriched": True, "size_sqft": None, "price_per_sqft": None,
        "comparable_valuation_low": 135000, "comparable_valuation_mid": 150000, "comparable_valuation_high": 165000,
        "comparable_confidence": 72, "comparable_count": 7, "comparable_provider": "HM Land Registry PPD",
    }
    result = underwrite_property(lot, analysis, assumptions={"refurb_cost": 15000}, strategy="residential")
    assert result["market_value"] == 150000
    assert result["auto_comparable_used"] is True
    assert "HM Land Registry" in result["market_value_basis"]
    assert result["max_bid"] is not None


def test_commercial_auto_comparables_require_explicit_opt_in():
    lot = {"property_type": "Industrial", "guide_price": 400000, "status": "Live", "raw_text": "freehold warehouse"}
    analysis = {
        "opening_offer": 360000, "features": {}, "tenure": "Freehold", "failure_count": 0,
        "detail_enriched": True, "size_sqft": 10000, "price_per_sqft": 40,
        "comparable_valuation_mid": 600000, "comparable_unit_psf_mid": 60,
        "comparable_confidence": 68, "comparable_count": 5, "comparable_provider": "Tracked auction results",
    }
    no_auto = underwrite_property(lot, analysis, assumptions={}, strategy="commercial")
    assert no_auto["market_value"] is None
    yes_auto = underwrite_property(lot, analysis, assumptions={"use_auto_comps": 1}, strategy="commercial")
    assert yes_auto["market_value"] == 600000
    assert yes_auto["auto_comparable_used"] is True
