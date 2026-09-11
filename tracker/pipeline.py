import requests

from .enrichment import fetch_detail_metadata, is_detail_url
from .geo import MotorwayNetwork, bulk_geocode, nearest_motorway
from .scrapers import SCRAPERS, Fetcher
from .comparables import refresh_due_comparables
from .diligence import refresh_due_diligence

COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}


def _enrich_geography(db, max_road_routes=60):
    rows = db.list_properties()
    postcodes = sorted({" ".join((r.get("postcode") or "").upper().split()) for r in rows if r.get("postcode")})
    cached = db.cached_postcodes(postcodes)
    missing = [p for p in postcodes if p not in cached]
    geocoded = 0
    geo_errors = []
    session = requests.Session()

    if missing:
        try:
            found = bulk_geocode(missing, session=session)
            for postcode, item in found.items():
                db.cache_postcode(postcode, item["latitude"], item["longitude"], item.get("source") or "Postcodes.io")
                geocoded += 1
        except Exception as exc:
            geo_errors.append(f"Postcode geocoding: {exc}")

    # Apply cached coordinates to any rows that pre-date the new columns.
    cached = db.cached_postcodes(postcodes)
    for postcode, item in cached.items():
        db.cache_postcode(postcode, item["latitude"], item["longitude"], item.get("source") or "Postcodes.io")

    rows = db.list_properties()
    needs_motorway = [
        r for r in rows
        if r.get("latitude") is not None and r.get("longitude") is not None and not r.get("motorway_updated_at")
    ]
    motorway_done = 0
    routed = 0
    fallback_air = 0
    if needs_motorway:
        try:
            junctions = MotorwayNetwork(session=session).load()
            if not junctions:
                raise RuntimeError("No North West motorway junctions returned by OpenStreetMap/Overpass")
            # Commercial rows first because road proximity is part of the acquisition strategy.
            needs_motorway.sort(key=lambda r: (0 if (r.get("property_type") or "").lower() in COMMERCIAL_TYPES else 1, r.get("id") or 0))
            for row in needs_motorway:
                commercial = (row.get("property_type") or "").lower() in COMMERCIAL_TYPES
                use_road = commercial and routed < max_road_routes
                info = nearest_motorway(
                    float(row["latitude"]), float(row["longitude"]), junctions,
                    session=session, road=use_road,
                )
                if info:
                    db.update_motorway(row["source_key"], info)
                    motorway_done += 1
                    if info.get("motorway_distance_kind") == "road":
                        routed += 1
                    else:
                        fallback_air += 1
        except Exception as exc:
            geo_errors.append(f"Motorway enrichment: {exc}")

    return {
        "postcodes_total": len(postcodes),
        "postcodes_newly_geocoded": geocoded,
        "motorway_enriched": motorway_done,
        "road_routed": routed,
        "straight_line_fallbacks": fallback_air,
        "errors": geo_errors,
    }


def refresh_all(db, selected=None):
    source_summary = []
    fetcher = Fetcher()

    for cls in SCRAPERS:
        if selected and cls.source not in selected:
            continue
        run = db.start_run(cls.source)
        try:
            lots = cls().scrape()
            changed = 0
            enriched = 0
            enrichment_errors = 0
            for lot in lots:
                lot_dict = lot.to_dict()
                is_changed = db.upsert(lot_dict)
                if is_changed:
                    changed += 1
                stored = db.property_for_key(lot.source_key)
                if stored and getattr(lot, "historical_events", None):
                    db.add_history_events(stored["id"], lot.historical_events)
                if is_detail_url(lot.url) and db.detail_due(lot.source_key, force=is_changed):
                    try:
                        detail = fetch_detail_metadata(lot.url, fetcher=fetcher)
                        if detail.get("text") or detail.get("image_url") or detail.get("auction_date"):
                            db.update_detail(
                                lot.source_key, detail.get("text") or "", detail.get("image_url") or "",
                                detail.get("auction_date") or "",
                            )
                            enriched += 1
                    except Exception:
                        # The catalogue row remains usable if a detail page temporarily fails.
                        enrichment_errors += 1
            db.finish_run(run, "ok", len(lots), "")
            source_summary.append({
                "source": cls.source,
                "status": "ok",
                "found": len(lots),
                "changed": changed,
                "detail_enriched": enriched,
                "detail_errors": enrichment_errors,
            })
        except Exception as exc:
            db.finish_run(run, "error", 0, str(exc)[:800])
            source_summary.append({
                "source": cls.source,
                "status": "error",
                "found": 0,
                "changed": 0,
                "detail_enriched": 0,
                "detail_errors": 0,
                "error": str(exc),
            })

    geography = _enrich_geography(db)
    current_rows = db.list_properties()
    comparables = refresh_due_comparables(db, rows=current_rows, max_properties=20)
    diligence = refresh_due_diligence(db, rows=current_rows, max_planning=15, max_legal=8)
    return {"sources": source_summary, "geography": geography, "comparables": comparables, "diligence": diligence}
