import math
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable

from dateutil import parser as date_parser


SQFT_RE = re.compile(
    r"(?P<n>[\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*ft\.?|sqft|square\s+feet|square\s+foot|ft2|ft\u00b2)",
    re.I,
)
SQM_RE = re.compile(
    r"(?P<n>[\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*m\.?|sqm|square\s+met(?:re|er)s?|m2|m\u00b2)",
    re.I,
)
OUTWARD_RE = re.compile(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\b", re.I)

COMMERCIAL_TYPES = {"industrial", "commercial", "mixed use", "development", "land"}
FAILURE_STATUSES = {"no bids", "last bid", "unsold", "available post-auction"}

# These are postcode-district corridor signals, not measured road distances. They are
# deliberately conservative and are shown in the UI as a signal, not an exact mileage.
STRONG_MOTORWAY_OUTWARDS = {
    # M65 / East Lancashire
    "BB1", "BB2", "BB3", "BB5", "BB6", "BB7", "BB8", "BB9", "BB10", "BB11", "BB12",
    # M6 / M61 / M65 Preston-Chorley
    "PR1", "PR2", "PR4", "PR5", "PR6", "PR7", "PR25", "PR26",
    # M61 / M60 / M66 Bolton-Bury
    "BL1", "BL2", "BL3", "BL4", "BL5", "BL6", "BL8", "BL9",
    # M60 / M62 / M602 / M56 Greater Manchester
    "M17", "M27", "M28", "M29", "M30", "M31", "M32", "M41", "M44", "M45",
    # M6 / M62 / M56 Warrington
    "WA1", "WA2", "WA3", "WA4", "WA5", "WA7", "WA8", "WA9",
    # M6 Wigan / Leigh corridor
    "WN2", "WN3", "WN4", "WN5", "WN7",
    # M53 / M56 Cheshire
    "CH1", "CH2", "CH65", "CH66", "CW1", "CW2", "CW7", "CW8", "CW9",
    # M57 / M58 Liverpool
    "L24", "L30", "L31", "L33", "L34", "L36",
    # M6 Lancaster / South Cumbria / Carlisle
    "LA1", "LA2", "LA5", "LA6", "LA7", "CA1", "CA2", "CA3",
}

MODERATE_MOTORWAY_AREAS = {"BB", "BL", "M", "PR", "WA", "WN", "CH", "CW", "L", "LA", "CA", "SK", "OL"}


@dataclass
class DealConfig:
    commercial_target_psf: int = 50
    commercial_ceiling_psf: int = 60
    commercial_min_sqft: int = 9000
    commercial_max_price: int = 1_500_000
    commercial_preferred_motorway_miles: float = 5.0
    residential_target_price: int = 100_000
    hot_score: float = 8.0

    def to_dict(self):
        return asdict(self)


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_size_sqft(text: str) -> int | None:
    text = text or ""
    values = []
    for match in SQFT_RE.finditer(text):
        try:
            n = float(match.group("n").replace(",", ""))
            if 50 <= n <= 5_000_000:
                values.append(n)
        except ValueError:
            pass
    for match in SQM_RE.finditer(text):
        try:
            n = float(match.group("n").replace(",", "")) * 10.7639104167
            if 50 <= n <= 5_000_000:
                values.append(n)
        except ValueError:
            pass
    if not values:
        return None
    # Auction descriptions can contain component areas. The largest stated area is the
    # safest proxy for the whole property when a total is present.
    return int(round(max(values)))


def infer_tenure(text: str) -> str:
    t = (text or "").lower()
    if "freehold" in t:
        return "Freehold"
    if "long leasehold" in t or "leasehold" in t:
        return "Leasehold"
    return "Unknown"


def detect_features(text: str) -> dict:
    t = (text or "").lower()
    return {
        "vacant": any(x in t for x in ["vacant", "vacant possession", "vacant property"]),
        "refurbishment": any(x in t for x in ["modernisation", "modernization", "refurbishment", "requires updating", "renovation", "in need of repair"]),
        "parking": any(x in t for x in ["parking", "car park", "car parking", "off-street parking", "off street parking"]),
        "loading": any(x in t for x in ["loading", "loading bay", "roller shutter", "yard", "service yard", "dock level"]),
        "split_potential": any(x in t for x in ["split", "subdivide", "sub-divide", "multiple units", "multi-let", "multi let", "separate units", "separate entrances", "part let"]),
        "development": any(x in t for x in ["development potential", "redevelopment", "planning permission", "subject to planning", "alternative use"]),
        "listed_building": any(x in t for x in ["grade i listed", "grade ii listed", "grade ii* listed", "listed building", "listed property"]),
    }


def _outward(postcode: str) -> str:
    m = OUTWARD_RE.search((postcode or "").upper())
    return m.group(1).upper() if m else ""


def motorway_access_signal(text: str, postcode: str = "") -> tuple[str, str]:
    t = (text or "").lower()
    explicit = re.search(r"\b(?:m6|m53|m56|m57|m58|m60|m61|m62|m65|m66|m67|a580)\b", t)
    if explicit or any(x in t for x in ["motorway", "motorway junction", "junction of the m"]):
        return "Strong", "Listing explicitly references a major motorway/strategic route."
    outward = _outward(postcode)
    if outward in STRONG_MOTORWAY_OUTWARDS:
        return "Strong", "Postcode sits in a recognised North West motorway corridor."
    area = re.match(r"[A-Z]+", outward)
    if area and area.group(0) in MODERATE_MOTORWAY_AREAS:
        return "Moderate", "North West postcode area has motorway access, but exact distance is not measured."
    return "Unknown", "No motorway-access signal found in the listing data."


def _parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    try:
        dt = date_parser.parse(text, dayfirst=True, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def history_metrics(history: Iterable[dict] | None, current: dict | None = None, now=None) -> dict:
    rows = list(history or [])
    rows.sort(key=lambda x: _parse_dt(x.get("captured_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if current:
        latest = {
            "captured_at": current.get("last_seen"),
            "guide_price": current.get("guide_price"),
            "result_price": current.get("result_price"),
            "status": current.get("status"),
            "auction_date": current.get("auction_date"),
        }
        if not rows or any(rows[-1].get(k) != latest.get(k) for k in ["guide_price", "result_price", "status", "auction_date"]):
            rows.append(latest)

    guide_values = [int(r["guide_price"]) for r in rows if _num(r.get("guide_price")) and _num(r.get("guide_price")) > 0]
    price_reduction_events = 0
    price_increase_events = 0
    previous = None
    for value in guide_values:
        if previous is not None:
            if value < previous:
                price_reduction_events += 1
            elif value > previous:
                price_increase_events += 1
        previous = value

    earliest = guide_values[0] if guide_values else None
    latest = guide_values[-1] if guide_values else None
    reduction_pct = 0.0
    if earliest and latest and latest < earliest:
        reduction_pct = round((earliest - latest) / earliest * 100, 1)

    statuses = [(r.get("status") or "").strip().lower() for r in rows]
    relist_count = sum(s == "relisted" for s in statuses)

    # Count distinct failed-auction events, not just status labels. Current unsold pages
    # often show "Available post-auction" while the archive shows "No Bids" for the
    # same auction. Merge those when their guide/date evidence overlaps, but count a
    # later post-auction appearance at a different guide/date as a new failed attempt.
    failure_events = []
    for r in rows:
        status = (r.get("status") or "").strip().lower()
        if status not in FAILURE_STATUSES:
            continue
        auction_dt = _parse_dt(r.get("auction_date"))
        captured_dt = _parse_dt(r.get("captured_at"))
        guide = int(_num(r.get("guide_price"))) if _num(r.get("guide_price")) else None
        event = {"auction_dt": auction_dt, "captured_dt": captured_dt, "guide": guide}
        duplicate = False
        for existing in failure_events:
            if auction_dt and existing["auction_dt"] and auction_dt.date() == existing["auction_dt"].date():
                duplicate = True
                break
            # If one representation lacks an auction date, identical guide evidence is
            # the best available signal that it is the same failed sale rather than a
            # second failure. Two dated auctions at the same guide still count twice.
            if guide and existing["guide"] == guide and (not auction_dt or not existing["auction_dt"]):
                duplicate = True
                if auction_dt and not existing["auction_dt"]:
                    existing["auction_dt"] = auction_dt
                break
        if not duplicate:
            failure_events.append(event)
    failure_count = len(failure_events)

    failure_dates = []
    for event in failure_events:
        dt = event.get("auction_dt") or event.get("captured_dt")
        if dt:
            failure_dates.append(dt)
    days_since_failure = None
    if failure_dates:
        now = now or datetime.now(timezone.utc)
        days_since_failure = max(0, (now - max(failure_dates)).days)

    return {
        "history_points": len(rows),
        "failure_count": failure_count,
        "relist_count": relist_count,
        "price_reduction_events": price_reduction_events,
        "price_increase_events": price_increase_events,
        "price_reduction_pct": reduction_pct,
        "earliest_guide": earliest,
        "latest_guide": latest,
        "days_since_failure": days_since_failure,
    }


def _status_points(status: str) -> tuple[int, str | None]:
    s = (status or "").lower()
    if s == "available post-auction":
        return 30, "Confirmed available after auction"
    if s == "no bids":
        return 27, "Auction recorded no bids"
    if s == "unsold":
        return 26, "Auction recorded the lot as unsold"
    if s == "last bid":
        return 24, "Auction finished with a last-bid / reserve-gap signal"
    if s == "relisted":
        return 18, "Relisted after an earlier failed/result state"
    if s == "withdrawn":
        return 5, "Withdrawn lot may justify an availability check"
    if s == "postponed":
        return 3, "Postponed lot may return to market"
    if s == "sold after":
        return 0, None
    if s in {"sold", "sold prior"}:
        return 0, None
    return 2, "Currently live at auction"


def _round_offer(value: float | int | None) -> int | None:
    if not value or value <= 0:
        return None
    step = 1_000 if value < 500_000 else 5_000
    return int(round(value / step) * step)


def negotiation_opener(lot: dict, metrics: dict) -> int | None:
    status = (lot.get("status") or "").lower()
    guide = _num(lot.get("guide_price"))
    result = _num(lot.get("result_price"))
    if status in {"sold", "sold prior", "sold after", "withdrawn", "postponed"}:
        return None
    if status == "last bid" and result:
        base = result * 0.96
    elif guide:
        factor = {
            "available post-auction": 0.85,
            "no bids": 0.82,
            "last bid": 0.85,
            "relisted": 0.88,
            "live": 0.90,
        }.get(status, 0.90)
        base = guide * factor
    else:
        return None
    extra_failures = max(0, metrics.get("failure_count", 0) - 1)
    base *= max(0.90, 1 - 0.02 * min(extra_failures, 3))
    return _round_offer(base)


def _add(points, reasons, value, label):
    if value:
        points += value
        reasons.append(f"+{value}: {label}")
    return points


def score_property(lot: dict, history=None, strategy="auto", config: DealConfig | None = None) -> dict:
    config = config or DealConfig()
    catalogue_raw = " ".join([str(lot.get("title") or ""), str(lot.get("address") or ""), str(lot.get("raw_text") or "")])
    detail_raw = str(lot.get("detail_text") or "")
    raw = " ".join([catalogue_raw, detail_raw])
    typ = (lot.get("property_type") or "Other").lower()
    selected = strategy
    if strategy == "auto":
        selected = "commercial" if typ in COMMERCIAL_TYPES else "residential"

    size = extract_size_sqft(raw)
    size_source = "Detail page" if detail_raw and extract_size_sqft(detail_raw) else ("Catalogue" if size else "Unknown")
    price = _num(lot.get("guide_price"))
    psf = round(price / size, 2) if price and size else None
    tenure = infer_tenure(raw)
    tenure_source = "Detail page" if detail_raw and infer_tenure(detail_raw) != "Unknown" else ("Catalogue" if tenure != "Unknown" else "Unknown")
    features = detect_features(raw)

    road_miles = _num(lot.get("motorway_road_miles"))
    air_miles = _num(lot.get("motorway_air_miles"))
    measured_miles = road_miles if road_miles is not None else air_miles
    distance_kind = lot.get("motorway_distance_kind") or ("road" if road_miles is not None else ("straight-line" if air_miles is not None else ""))
    nearest_motorway = lot.get("nearest_motorway") or ""
    nearest_junction = lot.get("nearest_junction") or ""
    if measured_miles is not None:
        if measured_miles <= 5:
            motorway = "Strong"
        elif measured_miles <= 10:
            motorway = "Moderate"
        elif measured_miles <= 15:
            motorway = "Fair"
        else:
            motorway = "Distant"
        label = nearest_junction or nearest_motorway or "motorway junction"
        motorway_note = f"{measured_miles:.1f} {distance_kind} miles to {label}."
    else:
        motorway, motorway_note = motorway_access_signal(raw, lot.get("postcode") or "")
    hm = history_metrics(history, current=lot)

    points = 0
    reasons = []
    warnings = []

    status_pts, status_reason = _status_points(lot.get("status") or "")
    points = _add(points, reasons, status_pts, status_reason)

    if hm["failure_count"] >= 2:
        bonus = min(12, (hm["failure_count"] - 1) * 6)
        points = _add(points, reasons, bonus, f"Repeated failed-auction history ({hm['failure_count']} failure signals)")
    if hm["price_reduction_pct"] >= 20:
        points = _add(points, reasons, 15, f"Guide reduced {hm['price_reduction_pct']}% from first observed guide")
    elif hm["price_reduction_pct"] >= 10:
        points = _add(points, reasons, 10, f"Guide reduced {hm['price_reduction_pct']}% from first observed guide")
    elif hm["price_reduction_pct"] >= 5:
        points = _add(points, reasons, 6, f"Guide reduced {hm['price_reduction_pct']}% from first observed guide")
    if hm["days_since_failure"] is not None:
        d = hm["days_since_failure"]
        if d <= 21:
            points = _add(points, reasons, 5, f"Recent failed/post-auction signal ({d} days ago)")
        elif d <= 60:
            points = _add(points, reasons, 3, f"Post-auction signal still relatively recent ({d} days)")
        else:
            points = _add(points, reasons, 1, f"Older unresolved post-auction signal ({d} days)")

    if selected == "commercial":
        if typ in COMMERCIAL_TYPES:
            points = _add(points, reasons, 3, "Commercial / industrial / development type")
        if price and price <= config.commercial_max_price:
            points = _add(points, reasons, 3, f"Guide is within the configured commercial ceiling of GBP {config.commercial_max_price:,.0f}")
        if size:
            if size >= config.commercial_min_sqft:
                points = _add(points, reasons, 12, f"Size {size:,} sq ft meets the {config.commercial_min_sqft:,}+ sq ft target")
            elif size >= 6000:
                points = _add(points, reasons, 7, f"Useful commercial size at {size:,} sq ft")
            elif size >= 3000:
                points = _add(points, reasons, 3, f"Moderate commercial size at {size:,} sq ft")
        else:
            warnings.append("Floor area not found in captured listing text; GBP/sq ft cannot yet be scored.")
        if psf is not None:
            if psf <= config.commercial_target_psf:
                points = _add(points, reasons, 18, f"Guide equates to GBP {psf:,.0f}/sq ft, at/below target")
            elif psf <= config.commercial_ceiling_psf:
                points = _add(points, reasons, 13, f"Guide equates to GBP {psf:,.0f}/sq ft, within ceiling")
            elif psf <= 75:
                points = _add(points, reasons, 6, f"Guide equates to GBP {psf:,.0f}/sq ft")
        if tenure == "Freehold":
            points = _add(points, reasons, 5, "Freehold")
        if features["parking"]:
            points = _add(points, reasons, 4, "Parking identified")
        if features["loading"]:
            points = _add(points, reasons, 4, "Yard/loading access signal")
        if features["split_potential"]:
            points = _add(points, reasons, 6, "Potential to split / multi-let identified")
        if features["vacant"]:
            points = _add(points, reasons, 3, "Vacant possession signal")
        if features["development"]:
            points = _add(points, reasons, 3, "Development / alternative-use potential")
        if measured_miles is not None:
            if measured_miles <= 2:
                points = _add(points, reasons, 8, f"Very close motorway access: {measured_miles:.1f} {distance_kind} miles to {nearest_junction or nearest_motorway}")
            elif measured_miles <= config.commercial_preferred_motorway_miles:
                points = _add(points, reasons, 6, f"Preferred motorway access: {measured_miles:.1f} {distance_kind} miles to {nearest_junction or nearest_motorway}")
            elif measured_miles <= 10:
                points = _add(points, reasons, 3, f"Useful motorway access: {measured_miles:.1f} {distance_kind} miles to {nearest_junction or nearest_motorway}")
            elif measured_miles <= 15:
                points = _add(points, reasons, 1, f"Motorway access within {measured_miles:.1f} {distance_kind} miles")
        elif motorway == "Strong":
            points = _add(points, reasons, 5, "Strong motorway-corridor signal (exact distance not yet enriched)")
        elif motorway == "Moderate":
            points = _add(points, reasons, 2, "Moderate motorway-corridor signal (exact distance not yet enriched)")
    else:
        if price:
            if price <= config.residential_target_price:
                points = _add(points, reasons, 20, f"Guide is at/below residential target of GBP {config.residential_target_price:,.0f}")
            elif price <= config.residential_target_price * 1.25:
                points = _add(points, reasons, 12, "Guide is close to residential acquisition target")
            elif price <= config.residential_target_price * 1.5:
                points = _add(points, reasons, 6, "Guide remains within a moderate flip-acquisition band")
        if typ == "house":
            points = _add(points, reasons, 4, "House type")
        if features["vacant"]:
            points = _add(points, reasons, 7, "Vacant possession signal")
        if features["refurbishment"]:
            points = _add(points, reasons, 9, "Modernisation / refurbishment opportunity")
        if tenure == "Freehold":
            points = _add(points, reasons, 4, "Freehold")
        if features["development"]:
            points = _add(points, reasons, 3, "Development / extension potential")

    # Convert a deliberately broad 100-point evidence score to 0-10.
    score_100 = min(100, max(0, points))
    score_10 = round(score_100 / 10, 1)

    confidence = 35
    if price:
        confidence += 15
    if lot.get("status"):
        confidence += 10
    if tenure != "Unknown":
        confidence += 8
    if hm["history_points"] >= 2:
        confidence += 12
    if selected == "commercial" and size:
        confidence += 15
    if selected == "commercial" and psf is not None:
        confidence += 5
    if selected == "residential" and (features["vacant"] or features["refurbishment"]):
        confidence += 8
    confidence = min(100, confidence)

    if road_miles is not None:
        confidence += 5
    elif air_miles is not None:
        warnings.append("Motorway distance is straight-line because road routing was unavailable; it is not driving mileage.")
    elif motorway != "Unknown":
        warnings.append("Motorway access is currently a postcode/listing signal because junction-distance enrichment is not yet available for this lot.")
    if detail_raw:
        confidence += 5
    if hm["history_points"] <= 1:
        warnings.append("Limited change history so far; repeat-failure and price-reduction scoring will strengthen after more refreshes.")

    confidence = min(100, confidence)
    opener = negotiation_opener(lot, hm)
    return {
        "deal_score": score_10,
        "deal_score_100": score_100,
        "strategy": selected.title(),
        "confidence": confidence,
        "size_sqft": size,
        "size_source": size_source,
        "price_per_sqft": psf,
        "tenure": tenure,
        "tenure_source": tenure_source,
        "detail_enriched": bool(detail_raw),
        "detail_enriched_at": lot.get("detail_enriched_at"),
        "motorway_signal": motorway,
        "motorway_note": motorway_note,
        "nearest_motorway": nearest_motorway,
        "nearest_junction": nearest_junction,
        "motorway_distance_miles": measured_miles,
        "motorway_distance_kind": distance_kind,
        "features": features,
        "failure_count": hm["failure_count"],
        "relist_count": hm["relist_count"],
        "price_reduction_events": hm["price_reduction_events"],
        "price_reduction_pct": hm["price_reduction_pct"],
        "days_since_failure": hm["days_since_failure"],
        "opening_offer": opener,
        "reasons": reasons,
        "warnings": warnings,
        "is_hot": score_10 >= config.hot_score,
    }
