from datetime import datetime, timezone
from pathlib import Path

from tracker.db import Database
from tracker.deal_engine import history_metrics
from tracker.enrichment import extract_detail_metadata
from tracker.planning import summarise_applications
from tracker.underwriting import (
    acquisition_costs,
    extract_listing_fees,
    known_risk_flags,
    underwrite_property,
)


def _lot(source_key="test-1", **overrides):
    lot = {
        "source": "Auction House NW",
        "source_key": source_key,
        "url": "https://www.auctionhouse.co.uk/northwest/auction/lot/150339",
        "title": "Lot 79 Guide | £150,000 Pub 162-164 Leigh Road, Leigh WN7 1SJ",
        "address": "162-164 Leigh Road, Leigh WN7 1SJ",
        "postcode": "WN7 1SJ",
        "area": "Greater Manchester",
        "property_type": "Commercial",
        "lot_number": "79",
        "guide_text": "£150,000",
        "guide_price": 150000,
        "result_text": "",
        "result_price": None,
        "status": "Available post-auction",
        "auction_date": "8 Sep 2026",
        "raw_text": "Vacant freehold pub 3,767 sq ft",
        "image_url": "",
    }
    lot.update(overrides)
    return lot


def test_detail_metadata_prefers_social_property_image():
    html = '''
    <html><head><meta property="og:image" content="/media/property-hero.jpg"></head>
    <body><main><h1>35 Wool Road</h1><img src="/images/logo.png" alt="Logo"></main></body></html>
    '''
    result = extract_detail_metadata(html, "https://www.auctionhouse.co.uk/manchester/auction/lot/151018")
    assert result["image_url"] == "https://www.auctionhouse.co.uk/media/property-hero.jpg"
    assert "35 Wool Road" in result["text"]


def test_history_backfill_counts_failures_and_guide_reduction(tmp_path: Path):
    db = Database(tmp_path / "history.db")
    db.upsert(_lot())
    row = db.property_for_key("test-1")
    events = [
        {
            "captured_at": "2026-06-10T00:00:00+00:00",
            "guide_text": "£170,000",
            "guide_price": 170000,
            "result_text": "Unsold",
            "result_price": None,
            "status": "Unsold",
            "auction_date": "10 Jun 2026",
        },
        {
            "captured_at": "2026-07-15T00:00:00+00:00",
            "guide_text": "£150,000",
            "guide_price": 150000,
            "result_text": "No Bids",
            "result_price": None,
            "status": "No Bids",
            "auction_date": "15 Jul 2026",
        },
    ]
    assert db.add_history_events(row["id"], events) == 2
    assert db.add_history_events(row["id"], events) == 0
    metrics = history_metrics(
        db.history_for(row["id"]),
        current=db.property_for_key("test-1"),
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    assert metrics["failure_count"] >= 2
    assert metrics["earliest_guide"] == 170000
    assert metrics["latest_guide"] == 150000
    assert metrics["price_reduction_pct"] == 11.8


def test_refurbishment_signal_blocks_approved_bid_ceiling():
    lot = {
        "property_type": "House",
        "guide_price": 180000,
        "status": "Available post-auction",
        "raw_text": "Three bedroom end terrace requiring modernisation and upgrading",
    }
    analysis = {
        "opening_offer": 153000,
        "failure_count": 2,
        "price_reduction_pct": 7.7,
        "features": {"vacant": True, "refurbishment": True},
        "tenure": "Freehold",
        "detail_enriched": True,
        "comparable_confidence": 75,
        "comparable_count": 8,
        "comparable_valuation_mid": 292000,
        "comparable_provider": "HM Land Registry PPD",
        "legal_status": "parsed",
        "legal_risk_score": 1,
        "planning_status": "ok",
        "planning_risk_score": 1,
    }
    result = underwrite_property(lot, analysis, assumptions={"refurb_cost": 0}, strategy="residential")
    assert result["recommendation"] == "WATCH"
    assert result["financial_score"] <= 4.0
    assert result["works_missing"] is True
    assert result["max_bid"] is not None
    assert result["max_bid_provisional"] is True
    assert result["bid_ceiling_approved"] is False
    assert "works estimate" in result["recommended_action"].lower()


def test_auctionhouse_fee_extraction_and_minimum_applied():
    lot = {
        "detail_text": "Administration Fee 1.5% incl VAT subject to minimum £2,100. Search fees £360 incl VAT."
    }
    fees = extract_listing_fees(lot)
    assert fees["buyer_premium_pct"] == 1.5
    assert fees["buyer_premium_minimum"] == 2100
    assert fees["search_fee"] == 360
    costs = acquisition_costs(
        100000,
        "residential",
        {
            "buyer_premium_pct": fees["buyer_premium_pct"],
            "buyer_premium_minimum": fees["buyer_premium_minimum"],
            "search_fee": fees["search_fee"],
            "auction_admin_fee": 0,
            "finance_mode": "Cash",
        },
    )
    # 1.5% of £100k is £1,500, so the £2,100 minimum must win.
    assert costs["buyer_premium"] == 2100
    assert costs["search_fee"] == 360


def test_listed_building_is_a_material_known_risk():
    flags = known_risk_flags({"detail_text": "Grade II Listed property requiring modernisation"})
    listed = [f for f in flags if "Listed-building" in f["label"]]
    assert listed
    assert listed[0]["severity"] >= 3


def test_planning_range_address_matches_named_property_but_not_neighbour():
    subject = "162-164 Leigh Road, Leigh WN7 1SJ"
    apps = [
        {
            "reference": "A/25/099497/FULL",
            "point": "POINT (-2.5200 53.4970)",
            "address-text": "Hilton Park, 162-164 Leigh Road, Leigh WN7 1SJ",
            "description": "Change of use to 13 person HMO",
            "planning-decision": "Refused",
            "start-date": "2025-10-01",
        },
        {
            "reference": "A/26/OTHER",
            "point": "POINT (-2.5201 53.4970)",
            "address-text": "160 Leigh Road, Leigh WN7 1SJ",
            "description": "Single storey extension",
            "planning-decision": "Approved",
            "start-date": "2026-01-01",
        },
    ]
    items, _ = summarise_applications(apps, 53.4970, -2.5200, "WN7 1SJ", subject)
    by_ref = {x["reference"]: x for x in items}
    assert by_ref["A/25/099497/FULL"]["likely_subject"] is True
    assert by_ref["A/25/099497/FULL"]["severity"] == 3
    assert by_ref["A/26/OTHER"]["likely_subject"] is False


def test_shortlist_persists_and_can_be_removed(tmp_path: Path):
    db = Database(tmp_path / "shortlist.db")
    db.upsert(_lot())
    pid = db.property_for_key("test-1")["id"]
    db.set_shortlisted(pid, True)
    assert pid in db.shortlist_ids()
    db.set_shortlisted(pid, False)
    assert pid not in db.shortlist_ids()

class _FakeAuctionResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url


class _FakeAuctionFetcher:
    def get(self, url):
        if url.endswith('/unsold'):
            return _FakeAuctionResponse('''
            <html><body><a href="/manchester/auction/lot/151018">
            Lot 28 *Guide | £180,000+ (plus fees) 3 Bed End of Terrace House
            35 Wool Road, Dobcross, Saddleworth, OL3 5NS
            </a></body></html>
            ''', url)
        if 'manchester/auction/past-auctions?page=1' in url:
            return _FakeAuctionResponse('''
            <table><tr><th>Address</th><th>Auction Ended</th><th>Guide</th><th>Result</th></tr>
            <tr><td>35 Wool Road, Dobcross, Saddleworth, OL3 5NS</td><td>14/07/2026 12:00</td><td>£195,000</td><td>No Bids</td></tr>
            </table>
            ''', url)
        return _FakeAuctionResponse('<html><body></body></html>', url)


def test_auctionhouse_backfill_includes_manchester_archive():
    from tracker.scrapers import AuctionHouseScraper

    lots = AuctionHouseScraper(fetcher=_FakeAuctionFetcher()).scrape()
    subject = next(x for x in lots if x.postcode == 'OL3 5NS')
    assert subject.status == 'Available post-auction'
    assert subject.guide_price == 180000
    assert subject.historical_events
    event = subject.historical_events[0]
    assert event['guide_price'] == 195000
    assert event['status'] == 'No Bids'
    assert event['auction_date'] == '14/07/2026 12:00'
    assert event['captured_at'].startswith('2026-07-14')


def test_post_auction_availability_is_continuation_not_new_failure_even_if_guide_changed():
    history = [{
        "captured_at": "2026-07-14T12:00:00+00:00",
        "guide_price": 195000,
        "status": "No Bids",
        "auction_date": "14/07/2026 12:00",
    }]
    current = {
        "last_seen": "2026-09-11T00:00:00+00:00",
        "guide_price": 180000,
        "status": "Available post-auction",
        "auction_date": "08/09/2026 12:00",
    }
    result = history_metrics(history, current=current, now=datetime(2026, 9, 11, tzinfo=timezone.utc))
    # Availability after auction is a marketing state, not evidence of a separate
    # auction attempt. A second failure needs a second concrete result record.
    assert result["failure_count"] == 1
    assert result["price_reduction_pct"] == 7.7


def test_two_concrete_failed_auction_dates_count_as_two_attempts():
    history = [
        {"captured_at": "2026-07-14T12:00:00+00:00", "guide_price": 195000, "status": "No Bids", "auction_date": "14/07/2026 12:00"},
        {"captured_at": "2026-09-08T12:00:00+00:00", "guide_price": 180000, "status": "Unsold", "auction_date": "08/09/2026 12:00"},
    ]
    result = history_metrics(history, now=datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["failure_count"] == 2
    assert result["price_reduction_pct"] == 7.7


def test_available_status_does_not_double_count_same_failed_auction():
    history = [{
        "captured_at": "2026-09-08T12:00:00+00:00",
        "guide_price": 180000,
        "status": "No Bids",
        "auction_date": "08/09/2026 12:00",
    }]
    current = {
        "last_seen": "2026-09-11T00:00:00+00:00",
        "guide_price": 180000,
        "status": "Available post-auction",
        "auction_date": "",
    }
    result = history_metrics(history, current=current, now=datetime(2026, 9, 11, tzinfo=timezone.utc))
    assert result["failure_count"] == 1


def test_detail_metadata_extracts_auction_date():
    html = '''<html><head><meta property="og:image" content="/hero.jpg"></head>
    <body><main>Auction Date Tue 08/09/2026 Auction Time 12:00 35 Wool Road</main></body></html>'''
    result = extract_detail_metadata(html, "https://www.auctionhouse.co.uk/manchester/auction/lot/151018")
    assert result["auction_date"] == "08/09/2026"


def test_detail_auction_date_survives_catalogue_refresh_without_false_change(tmp_path: Path):
    db = Database(tmp_path / "dates.db")
    lot = _lot(auction_date="")
    assert db.upsert(lot) is True
    db.update_detail("test-1", "Auction Date 08/09/2026", "https://example.test/hero.jpg", "08/09/2026")
    assert db.property_for_key("test-1")["auction_date"] == "08/09/2026"
    # The catalogue/unsold card may not include the date. It must not erase the richer detail value
    # or produce a spurious 'changed' record on every refresh.
    assert db.upsert(_lot(auction_date="")) is False
    assert db.property_for_key("test-1")["auction_date"] == "08/09/2026"
