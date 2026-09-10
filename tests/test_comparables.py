from datetime import date

from tracker.comparables import (
    LandRegistryPPDProvider,
    infer_residential_subtype,
    summarise_residential_comps,
    internal_auction_comparables,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        if "postcodes.io" in url:
            return FakeResponse({"result": [
                {"postcode": "BB2 4BZ", "distance": 0},
                {"postcode": "BB2 4AA", "distance": 410},
            ]})
        return FakeResponse({"results": {"bindings": [
            {
                "item": {"value": "http://example/txn/1"},
                "paon": {"value": "12"}, "street": {"value": "TEST ROAD"}, "town": {"value": "BLACKBURN"},
                "postcode": {"value": "BB2 4AA"}, "amount": {"value": "145000"}, "date": {"value": "2026-01-15"},
                "propertyType": {"value": "http://landregistry.data.gov.uk/def/common/terraced"},
                "estateType": {"value": "http://landregistry.data.gov.uk/def/common/freehold"},
            }
        ]}})


def test_infer_residential_subtype():
    assert infer_residential_subtype({"property_type": "House", "detail_text": "three bedroom semi-detached house"}) == "Semi-Detached"
    assert infer_residential_subtype({"property_type": "Flat"}) == "Flat/Maisonette"


def test_residential_summary_weighted_range():
    subject = {"property_type": "House", "detail_text": "terraced house", "postcode": "BB2 4BZ", "guide_price": 90000}
    comps = [
        {"address": "1 A St", "postcode": "BB2 4AA", "sale_price": 135000, "sale_date": "2026-05-01", "property_type": "Terraced", "distance_miles": .3},
        {"address": "2 A St", "postcode": "BB2 4AB", "sale_price": 145000, "sale_date": "2026-01-01", "property_type": "Terraced", "distance_miles": .4},
        {"address": "3 A St", "postcode": "BB2 4AC", "sale_price": 150000, "sale_date": "2025-08-01", "property_type": "Terraced", "distance_miles": .7},
        {"address": "4 A St", "postcode": "BB2 4AD", "sale_price": 160000, "sale_date": "2025-02-01", "property_type": "Terraced", "distance_miles": .8},
        {"address": "5 A St", "postcode": "BB2 4AE", "sale_price": 170000, "sale_date": "2024-12-01", "property_type": "Semi-Detached", "distance_miles": 1.1},
    ]
    s = summarise_residential_comps(subject, comps, today=date(2026, 9, 10))
    assert s["comp_count"] == 5
    assert 130000 <= s["valuation_low"] <= s["valuation_mid"] <= s["valuation_high"] <= 175000
    assert s["confidence"] >= 50
    assert s["guide_discount_pct"] > 30


def test_land_registry_provider_parses_json():
    session = FakeSession()
    provider = LandRegistryPPDProvider(session=session)
    result = provider.fetch({"property_type": "House", "detail_text": "terraced", "postcode": "BB2 4BZ", "guide_price": 100000}, today=date(2026, 9, 10))
    assert result["provider"] == "HM Land Registry PPD"
    assert result["comp_count"] == 1
    assert result["comps"][0]["sale_price"] == 145000
    assert result["comps"][0]["tenure"] == "Freehold"
    assert any("landregistry/query" in call[0] for call in session.calls)


class FakeDB:
    def list_properties(self):
        return [
            {"id": 1, "source_key": "subject", "status": "Live", "property_type": "Industrial", "latitude": 53.75, "longitude": -2.48, "detail_text": "10,000 sq ft warehouse"},
            {"id": 2, "source_key": "comp1", "status": "Sold", "result_price": 600000, "property_type": "Industrial", "latitude": 53.76, "longitude": -2.49, "detail_text": "10,000 sq ft warehouse", "auction_date": "1 Jun 2026", "address": "Unit A", "postcode": "BB1 1AA", "source": "Allsop", "url": "https://example/a"},
            {"id": 3, "source_key": "comp2", "status": "Sold", "result_price": 650000, "property_type": "Industrial", "latitude": 53.78, "longitude": -2.50, "detail_text": "10,500 sq ft industrial", "auction_date": "1 May 2026", "address": "Unit B", "postcode": "BB1 1AB", "source": "Savills", "url": "https://example/b"},
            {"id": 4, "source_key": "comp3", "status": "Sold", "result_price": 575000, "property_type": "Industrial", "latitude": 53.72, "longitude": -2.46, "detail_text": "9,500 sq ft warehouse", "auction_date": "1 Apr 2026", "address": "Unit C", "postcode": "BB1 1AC", "source": "Auction House NW", "url": "https://example/c"},
        ]


def test_internal_commercial_comparables_psf():
    db = FakeDB()
    subject = db.list_properties()[0]
    result = internal_auction_comparables(db, subject, today=date(2026, 9, 10))
    assert result["usable_psf_comp_count"] == 3
    assert 55 <= result["unit_psf_mid"] <= 65
    assert 550000 <= result["valuation_mid"] <= 650000
