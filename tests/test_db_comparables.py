from pathlib import Path

from tracker.db import Database


def _insert_property(db):
    db.upsert({
        "source": "Test", "source_key": "abc", "url": "https://example.com", "title": "Test house",
        "address": "1 Test Street BB1 1AA", "postcode": "BB1 1AA", "area": "Lancashire",
        "property_type": "House", "lot_number": "1", "guide_text": "£100,000", "guide_price": 100000,
        "result_text": "", "result_price": None, "status": "Live", "auction_date": "", "raw_text": "terraced house",
    })
    return db.property_for_key("abc")


def test_comparable_bundle_persists(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    row = _insert_property(db)
    db.save_comparable_bundle(row["id"], {
        "provider": "HM Land Registry PPD", "valuation_low": 140000, "valuation_mid": 150000,
        "valuation_high": 160000, "unit_psf_mid": None, "comp_count": 1, "confidence": 70,
        "guide_discount_pct": 33.3, "methodology": "test", "warnings": ["note"], "attribution": "attr",
    }, [{
        "provider": "HM Land Registry PPD", "source_ref": "http://example/txn", "address": "2 Test Street",
        "postcode": "BB1 1AB", "sale_price": 150000, "sale_date": "2026-01-01", "property_type": "Terraced",
        "tenure": "Freehold", "distance_miles": 0.2, "size_sqft": None, "price_per_sqft": None,
        "match_score": 90, "same_property": 0, "metadata": {"county": "LANCASHIRE"},
    }])
    summary = db.comparable_summary_for(row["id"])
    comps = db.comparables_for(row["id"])
    assert summary["valuation_mid"] == 150000
    assert summary["warnings"] == ["note"]
    assert comps[0]["sale_price"] == 150000
    assert comps[0]["metadata"]["county"] == "LANCASHIRE"
    assert db.comparables_due(row["id"], max_age_days=14) is False


def test_comparable_error_is_due_again(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    row = _insert_property(db)
    db.record_comparable_error(row["id"], "timeout")
    assert db.comparable_summary_for(row["id"])["status"] == "error"
    assert db.comparables_due(row["id"], max_age_days=14) is True
