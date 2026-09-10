from types import SimpleNamespace

from tracker.enrichment import extract_detail_text, fetch_detail_text
from tracker.geo import haversine_miles, nearest_motorway, MotorwayNetwork, bulk_geocode


def test_extract_detail_text_keeps_floor_area_and_tenure():
    html = """
    <html><body><main><h1>Warehouse</h1><p>Freehold industrial unit.</p>
    <p>GIA approximately 10,250 sq ft with yard and loading.</p><script>ignore me</script></main></body></html>
    """
    text = extract_detail_text(html)
    assert "10,250 sq ft" in text
    assert "Freehold" in text
    assert "ignore me" not in text


def test_fetch_detail_text_uses_allowed_auction_url():
    class FakeFetcher:
        def get(self, url):
            return SimpleNamespace(text="<main>GIA 9,500 sq ft. Tenure: Freehold.</main>")
    text = fetch_detail_text("https://www.allsop.co.uk/lot-overview/test/ABC", FakeFetcher())
    assert "9,500 sq ft" in text


def test_haversine_is_sensible():
    # Roughly Blackburn to Preston scale; only checking formula magnitude.
    miles = haversine_miles(53.75, -2.48, 53.76, -2.70)
    assert 8 < miles < 12


def test_nearest_motorway_prefers_nearest_when_road_disabled():
    junctions = [
        {"motorway": "M65", "label": "M65 J5", "latitude": 53.75, "longitude": -2.45},
        {"motorway": "M6", "label": "M6 J31", "latitude": 53.77, "longitude": -2.65},
    ]
    info = nearest_motorway(53.75, -2.48, junctions, road=False)
    assert info["nearest_motorway"] == "M65"
    assert info["motorway_distance_kind"] == "straight-line"


def test_bulk_geocode_parsing():
    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"result": [{"query": "BB1 2AA", "result": {"postcode": "BB1 2AA", "latitude": 53.75, "longitude": -2.48}}]}
    class Session:
        def post(self, *args, **kwargs): return Resp()
    result = bulk_geocode(["BB1 2AA"], session=Session())
    assert result["BB1 2AA"]["latitude"] == 53.75


def test_overpass_motorway_membership_parsing(tmp_path):
    payload = {
        "elements": [
            {"type": "way", "id": 1, "nodes": [10, 11], "tags": {"highway": "motorway", "ref": "M65"}},
            {"type": "node", "id": 10, "lat": 53.70, "lon": -2.40, "tags": {"highway": "motorway_junction", "ref": "5"}},
        ]
    }
    class Resp:
        def raise_for_status(self): pass
        def json(self): return payload
    class Session:
        def post(self, *args, **kwargs): return Resp()
    network = MotorwayNetwork(cache_path=tmp_path / "junctions.json", session=Session())
    junctions = network.fetch()
    assert len(junctions) == 1
    assert junctions[0]["motorway"] == "M65"
    assert junctions[0]["label"] == "M65 J5"
