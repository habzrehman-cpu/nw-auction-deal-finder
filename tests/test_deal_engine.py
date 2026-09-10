from datetime import datetime, timezone, timedelta

from tracker.deal_engine import (
    DealConfig,
    extract_size_sqft,
    history_metrics,
    motorway_access_signal,
    score_property,
)


def test_extract_size_sqft():
    assert extract_size_sqft("Industrial unit extending to 9,500 sq ft") == 9500
    assert 10760 <= extract_size_sqft("Total area 1,000 sqm") <= 10765


def test_history_reduction_and_failures():
    now = datetime.now(timezone.utc)
    hist = [
        {"captured_at": (now - timedelta(days=20)).isoformat(), "guide_price": 200000, "status": "Live"},
        {"captured_at": (now - timedelta(days=10)).isoformat(), "guide_price": 180000, "status": "No Bids"},
        {"captured_at": (now - timedelta(days=2)).isoformat(), "guide_price": 160000, "status": "Last Bid"},
    ]
    m = history_metrics(hist, now=now)
    assert m["failure_count"] == 2
    assert m["price_reduction_events"] == 2
    assert m["price_reduction_pct"] == 20.0
    assert m["days_since_failure"] == 2


def test_motorway_signal():
    level, _ = motorway_access_signal("Warehouse", "BB1 2AA")
    assert level == "Strong"
    level, _ = motorway_access_signal("Warehouse close to M6 junction", "XX1 1XX")
    assert level == "Strong"


def test_commercial_target_scores_high():
    lot = {
        "status": "Available post-auction",
        "property_type": "Industrial",
        "raw_text": "Vacant freehold industrial warehouse 10,000 sq ft with yard parking loading and potential to split units near M65",
        "title": "Industrial warehouse",
        "address": "Blackburn BB1 2AA",
        "postcode": "BB1 2AA",
        "guide_price": 450000,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    result = score_property(lot, [], strategy="commercial", config=DealConfig())
    assert result["price_per_sqft"] == 45.0
    assert result["deal_score"] >= 8.0
    assert result["opening_offer"] is not None


def test_sold_is_not_given_motivation_points():
    lot = {
        "status": "Sold",
        "property_type": "House",
        "raw_text": "vacant freehold house requiring modernisation",
        "guide_price": 60000,
    }
    result = score_property(lot, [], strategy="residential")
    assert result["deal_score"] < 8.0
    assert result["opening_offer"] is None


def test_detail_page_and_measured_motorway_upgrade_score():
    lot = {
        "status": "Available post-auction",
        "property_type": "Industrial",
        "raw_text": "Industrial property Blackburn BB1 2AA",
        "detail_text": "Freehold warehouse GIA 10,000 sq ft with parking yard loading and multiple units",
        "detail_enriched_at": datetime.now(timezone.utc).isoformat(),
        "postcode": "BB1 2AA",
        "guide_price": 450000,
        "motorway_road_miles": 3.2,
        "motorway_air_miles": 2.1,
        "motorway_distance_kind": "road",
        "nearest_motorway": "M65",
        "nearest_junction": "M65 J5",
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }
    result = score_property(lot, [], strategy="commercial", config=DealConfig())
    assert result["size_sqft"] == 10000
    assert result["size_source"] == "Detail page"
    assert result["price_per_sqft"] == 45.0
    assert result["motorway_distance_miles"] == 3.2
    assert result["nearest_junction"] == "M65 J5"
    assert result["deal_score"] >= 8.0
