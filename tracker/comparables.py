from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Iterable
from urllib.parse import quote

import requests
from dateutil import parser as date_parser

from .deal_engine import COMMERCIAL_TYPES, extract_size_sqft
from .geo import haversine_miles

PPD_ENDPOINT = "https://landregistry.data.gov.uk/landregistry/query"
POSTCODES_NEAREST = "https://api.postcodes.io/postcodes/{postcode}/nearest"
HMLR_ATTRIBUTION = "Contains HM Land Registry data © Crown copyright and database right 2021. This data is licensed under the Open Government Licence v3.0."

SOLD_STATUSES = {"sold", "sold after", "sold prior"}
HOUSE_PPD_TYPES = {"Detached", "Semi-Detached", "Terraced"}


@dataclass
class ComparableConfig:
    residential_years: int = 3
    residential_radius_metres: int = 2000
    residential_nearest_postcodes: int = 100
    residential_max_results: int = 500
    max_comps: int = 12
    commercial_years: int = 3
    commercial_max_distance_miles: float = 40.0
    commercial_max_size_ratio: float = 2.5


def _normalise_postcode(value: str) -> str:
    p = re.sub(r"\s+", "", (value or "").upper())
    return f"{p[:-3]} {p[-3:]}" if len(p) > 3 else p


def _money_round(value: float | None, step: int = 1000) -> int | None:
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return int(round(value / step) * step)


def _float(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass
    try:
        return date_parser.parse(str(value), dayfirst=True, fuzzy=True).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _months_between(earlier: date, later: date) -> float:
    return max(0.0, (later - earlier).days / 30.4375)


def infer_residential_subtype(lot: dict) -> str:
    typ = (lot.get("property_type") or "").strip().lower()
    text = " ".join(str(lot.get(k) or "") for k in ("title", "address", "raw_text", "detail_text")).lower()
    if typ == "flat" or any(term in text for term in ("flat", "apartment", "maisonette")):
        return "Flat/Maisonette"
    if "semi-detached" in text or "semi detached" in text:
        return "Semi-Detached"
    if "terraced" in text or "terrace house" in text or "mid-terrace" in text or "end-terrace" in text:
        return "Terraced"
    if "detached" in text and "semi" not in text:
        return "Detached"
    if typ == "house" or any(term in text for term in ("house", "bungalow", "cottage")):
        return "House"
    return "Other"


def _ppd_property_type(uri: str) -> str:
    token = (uri or "").rstrip("/").split("/")[-1].replace("_", "-").lower()
    mapping = {
        "detached": "Detached",
        "semi-detached": "Semi-Detached",
        "semidetached": "Semi-Detached",
        "terraced": "Terraced",
        "flat-maisonette": "Flat/Maisonette",
        "flat": "Flat/Maisonette",
        "other": "Other",
    }
    for key, label in mapping.items():
        if key in token:
            return label
    return token.replace("-", " ").title() if token else "Other"


def _ppd_estate_type(uri: str) -> str:
    token = (uri or "").rstrip("/").split("/")[-1].lower()
    if "freehold" in token:
        return "Freehold"
    if "leasehold" in token:
        return "Leasehold"
    return "Unknown"


def _binding_value(binding: dict, key: str, default=""):
    item = binding.get(key) or {}
    return item.get("value", default) if isinstance(item, dict) else default


def _address_from_binding(binding: dict) -> str:
    bits = [
        _binding_value(binding, "saon"),
        _binding_value(binding, "paon"),
        _binding_value(binding, "street"),
        _binding_value(binding, "town"),
    ]
    return ", ".join(str(x).strip() for x in bits if str(x).strip())


def _type_similarity(subject: str, comp: str) -> float:
    if subject == comp:
        return 1.0
    if subject == "House" and comp in HOUSE_PPD_TYPES:
        return 0.82
    if subject in HOUSE_PPD_TYPES and comp in HOUSE_PPD_TYPES:
        return 0.58
    if subject == "Other" or comp == "Other":
        return 0.35
    return 0.0


def _weighted_quantile(values: list[tuple[float, float]], quantile: float) -> float | None:
    clean = sorted((float(v), max(0.0, float(w))) for v, w in values if v and w is not None and float(w) > 0)
    if not clean:
        return None
    total = sum(w for _, w in clean)
    threshold = max(0.0, min(1.0, quantile)) * total
    running = 0.0
    for value, weight in clean:
        running += weight
        if running >= threshold:
            return value
    return clean[-1][0]


def _street_signature(value: str) -> str:
    text = " ".join((value or "").upper().replace(",", " , ").split())
    # Drop the first building number/name prefix, then keep the first address segment.
    text = re.sub(r"^.*?\b\d+[A-Z]?(?:\s*[-/]\s*\d+[A-Z]?)?\b\s*,?\s*", "", text, count=1)
    segment = text.split(" , ")[0]
    segment = re.sub(r"\b(ROAD|RD|STREET|ST|LANE|LN|AVENUE|AVE|DRIVE|DR|CLOSE|WAY|PLACE|PL)\b", lambda m: m.group(1), segment)
    return re.sub(r"[^A-Z0-9 ]", "", segment).strip()


def _same_street(subject: dict, comp: dict) -> bool:
    subject_text = str(subject.get("address") or subject.get("title") or "")
    a = _street_signature(subject_text)
    b = _street_signature(str(comp.get("address") or ""))
    return bool(a and b and (a == b or (len(a) >= 5 and (a in b or b in a))))


def _same_address(subject: dict, comp: dict) -> bool:
    subject_pc = _normalise_postcode(subject.get("postcode") or "")
    if subject_pc and subject_pc != _normalise_postcode(comp.get("postcode") or ""):
        return False
    subject_text = " ".join(str(subject.get(k) or "") for k in ("address", "title")).lower()
    comp_text = (comp.get("address") or "").lower()
    # Require a house/flat number match as well as postcode where possible.
    nums = re.findall(r"\b\d+[a-z]?\b", subject_text)
    return bool(nums and any(re.search(rf"\b{re.escape(n)}\b", comp_text) for n in nums))


def _trim_price_outliers(comps: list[dict]) -> list[dict]:
    prices = [float(c["sale_price"]) for c in comps if c.get("sale_price")]
    if len(prices) < 7:
        return comps
    med = median(prices)
    if med <= 0:
        return comps
    kept = [c for c in comps if 0.45 * med <= float(c.get("sale_price") or 0) <= 2.2 * med]
    return kept if len(kept) >= 4 else comps


def summarise_residential_comps(subject: dict, comps: list[dict], today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    comps = _trim_price_outliers([dict(c) for c in comps if c.get("sale_price")])
    subject_type = infer_residential_subtype(subject)
    ranked = []
    for c in comps:
        sold = _parse_date(c.get("sale_date"))
        if not sold:
            continue
        months = _months_between(sold, today)
        distance = max(0.0, _float(c.get("distance_miles"), 99.0) or 99.0)
        comp_type = c.get("property_type") or "Other"
        type_match = _type_similarity(subject_type, comp_type)
        if type_match <= 0:
            continue
        distance_weight = 1.0 if distance <= 0.25 else 0.92 if distance <= 0.5 else 0.78 if distance <= 1.0 else 0.62 if distance <= 1.5 else 0.45
        recency_weight = 1.0 if months <= 6 else 0.94 if months <= 12 else 0.82 if months <= 24 else 0.68
        same = bool(c.get("same_property")) or _same_address(subject, c)
        same_street = _same_street(subject, c)
        same_factor = 0.45 if same else 1.0
        street_factor = 1.18 if same_street and not same else 1.0
        weight = min(1.2, type_match * distance_weight * recency_weight * same_factor * street_factor)
        c.update({
            "months_ago": round(months, 1),
            "type_match": round(type_match, 2),
            "same_street": 1 if same_street else 0,
            "match_score": round(weight * 100, 1),
            "same_property": 1 if same else 0,
        })
        ranked.append(c)
    ranked.sort(key=lambda x: (x.get("match_score") or 0, -(x.get("distance_miles") or 0)), reverse=True)
    # If we have enough strong evidence, do not let weaker house subtypes or distant
    # sales widen the desktop range unnecessarily.
    exact_close = [c for c in ranked if (c.get("type_match") or 0) >= 0.99 and (c.get("distance_miles") or 99) <= 1.0 and not c.get("same_property")]
    if len(exact_close) >= 4:
        ranked = exact_close
    very_close = [c for c in ranked if (c.get("distance_miles") or 99) <= 0.5 and not c.get("same_property")]
    if len(very_close) >= 5:
        ranked = very_close
    ranked = ranked[:10]
    weighted = [(float(c["sale_price"]), max(0.01, float(c["match_score"]) / 100)) for c in ranked]
    mid = _weighted_quantile(weighted, 0.50)
    low = _weighted_quantile(weighted, 0.25)
    high = _weighted_quantile(weighted, 0.75)
    n = len(ranked)
    if n and mid:
        if n < 4:
            low = min(float(c["sale_price"]) for c in ranked)
            high = max(float(c["sale_price"]) for c in ranked)
        if low == high:
            low, high = mid * 0.93, mid * 1.07
    prices = [float(c["sale_price"]) for c in ranked]
    dispersion = ((max(prices) - min(prices)) / mid) if n >= 3 and mid else 1.0
    exact_ratio = sum((c.get("type_match") or 0) >= 0.99 for c in ranked) / n if n else 0
    recent_ratio = sum((c.get("months_ago") or 999) <= 18 for c in ranked) / n if n else 0
    close_ratio = sum((c.get("distance_miles") or 99) <= 1.0 for c in ranked) / n if n else 0
    same_street_ratio = sum(bool(c.get("same_street")) for c in ranked) / n if n else 0
    confidence = 18 + min(32, n * 4) + exact_ratio * 12 + recent_ratio * 10 + close_ratio * 8 + same_street_ratio * 8 - min(18, dispersion * 12)
    if n < 3:
        confidence = min(confidence, 42)
    confidence = int(max(0, min(82, round(confidence))))
    guide = _float(subject.get("guide_price"))
    discount = ((mid - guide) / mid * 100) if mid and guide else None
    warnings = [
        "HM Land Registry Price Paid Data does not include bedrooms, internal floor area or condition, so this is desktop comparable evidence rather than a formal valuation."
    ]
    if n < 5:
        warnings.append("Fewer than five usable nearby sold comparables were found; widen the evidence set or verify with local agent/RICS evidence before bidding.")
    if dispersion > 0.45:
        warnings.append("Comparable sale prices are widely dispersed, which reduces confidence in the automated range.")
    return {
        "provider": "HM Land Registry PPD",
        "methodology": "Nearby standard residential sales, weighted by exact subtype, same-street match, distance and recency, with weaker evidence removed when enough close exact-type sales exist.",
        "valuation_low": _money_round(low),
        "valuation_mid": _money_round(mid),
        "valuation_high": _money_round(high),
        "unit_psf_mid": None,
        "comp_count": n,
        "confidence": confidence,
        "guide_discount_pct": round(discount, 1) if discount is not None else None,
        "warnings": warnings,
        "attribution": HMLR_ATTRIBUTION,
        "comps": ranked,
    }


class LandRegistryPPDProvider:
    def __init__(self, session: requests.Session | None = None, timeout: int = 25, config: ComparableConfig | None = None):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.config = config or ComparableConfig()
        self.session.headers.setdefault("User-Agent", "NW-Auction-Deal-Finder/1.0")

    def nearest_postcodes(self, postcode: str) -> tuple[list[str], dict[str, float]]:
        postcode = _normalise_postcode(postcode)
        if not postcode:
            return [], {}
        url = POSTCODES_NEAREST.format(postcode=quote(postcode.replace(" ", "")))
        response = self.session.get(
            url,
            params={"limit": self.config.residential_nearest_postcodes, "radius": self.config.residential_radius_metres},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json() or {}
        rows = payload.get("result") or []
        postcodes, distances = [], {}
        for row in rows:
            pc = _normalise_postcode(row.get("postcode") or "")
            if not pc:
                continue
            postcodes.append(pc)
            metres = _float(row.get("distance"), 0.0) or 0.0
            distances[pc] = metres / 1609.344
        if postcode not in distances:
            postcodes.insert(0, postcode)
            distances[postcode] = 0.0
        return postcodes[:100], distances

    def _query(self, postcodes: Iterable[str], since: date) -> list[dict]:
        pcs = [_normalise_postcode(p) for p in postcodes if p]
        rows = []
        seen = set()
        # Keep GET query strings modest; the public endpoint accepts exact-postcode VALUES efficiently.
        for start in range(0, len(pcs), 45):
            batch = pcs[start:start + 45]
            values = " ".join(f'"{p}"^^xsd:string' for p in batch)
            if not values:
                continue
            query = f"""
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX ppd: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
SELECT ?item ?paon ?saon ?street ?town ?county ?postcode ?amount ?date ?estateType ?propertyType
WHERE {{
  VALUES ?postcode {{ {values} }}
  ?addr lrcommon:postcode ?postcode .
  ?item ppd:propertyAddress ?addr ;
        ppd:pricePaid ?amount ;
        ppd:transactionDate ?date ;
        ppd:transactionCategory ppd:standardPricePaidTransaction .
  FILTER (?date >= "{since.isoformat()}"^^xsd:date)
  OPTIONAL {{ ?item ppd:estateType ?estateType }}
  OPTIONAL {{ ?item ppd:propertyType ?propertyType }}
  OPTIONAL {{ ?addr lrcommon:paon ?paon }}
  OPTIONAL {{ ?addr lrcommon:saon ?saon }}
  OPTIONAL {{ ?addr lrcommon:street ?street }}
  OPTIONAL {{ ?addr lrcommon:town ?town }}
  OPTIONAL {{ ?addr lrcommon:county ?county }}
}}
ORDER BY DESC(?date)
LIMIT {int(self.config.residential_max_results)}
"""
            response = self.session.get(
                PPD_ENDPOINT,
                params={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json() or {}
            for binding in payload.get("results", {}).get("bindings", []) or []:
                ref = _binding_value(binding, "item") or json.dumps(binding, sort_keys=True)
                if ref in seen:
                    continue
                seen.add(ref)
                rows.append(binding)
        return rows

    def fetch(self, subject: dict, today: date | None = None) -> dict:
        postcode = _normalise_postcode(subject.get("postcode") or "")
        if not postcode:
            raise ValueError("Property has no postcode for comparable search")
        today = today or datetime.now(timezone.utc).date()
        since = today - timedelta(days=365 * self.config.residential_years + 1)
        nearest_warning = None
        try:
            postcodes, distances = self.nearest_postcodes(postcode)
        except requests.RequestException as exc:
            postcodes, distances = [postcode], {postcode: 0.0}
            nearest_warning = f"Postcodes.io nearest-postcode search was unavailable; evidence was limited to the subject postcode ({exc})."
        bindings = self._query(postcodes, since)
        comps = []
        for b in bindings:
            price = _float(_binding_value(b, "amount"))
            sold = _binding_value(b, "date")
            pc = _normalise_postcode(_binding_value(b, "postcode"))
            if not price or not sold or not pc:
                continue
            comp = {
                "provider": "HM Land Registry PPD",
                "source_ref": _binding_value(b, "item"),
                "address": _address_from_binding(b),
                "postcode": pc,
                "sale_price": int(round(price)),
                "sale_date": sold[:10],
                "property_type": _ppd_property_type(_binding_value(b, "propertyType")),
                "tenure": _ppd_estate_type(_binding_value(b, "estateType")),
                "distance_miles": round(float(distances.get(pc, 99.0)), 2),
                "size_sqft": None,
                "price_per_sqft": None,
                "same_property": 0,
                "metadata": {"county": _binding_value(b, "county")},
            }
            comps.append(comp)
        summary = summarise_residential_comps(subject, comps, today=today)
        if nearest_warning:
            summary.setdefault("warnings", []).append(nearest_warning)
        summary["searched_postcodes"] = len(postcodes)
        return summary


def _commercial_family(property_type: str) -> str:
    typ = (property_type or "").strip().lower()
    if typ == "industrial":
        return "industrial"
    if typ in {"commercial", "mixed use"}:
        return "commercial"
    if typ in {"land", "development"}:
        return "development"
    return typ or "other"


def _sale_date_for_row(row: dict) -> date | None:
    return _parse_date(row.get("auction_date")) or _parse_date(row.get("last_seen"))


def internal_auction_comparables(db, subject: dict, config: ComparableConfig | None = None, today: date | None = None) -> dict:
    config = config or ComparableConfig()
    today = today or datetime.now(timezone.utc).date()
    subject_size = extract_size_sqft(" ".join(str(subject.get(k) or "") for k in ("title", "raw_text", "detail_text")))
    subject_lat = _float(subject.get("latitude"))
    subject_lon = _float(subject.get("longitude"))
    subject_family = _commercial_family(subject.get("property_type") or "")
    since = today - timedelta(days=365 * config.commercial_years + 1)
    comps = []
    for row in db.list_properties():
        if row.get("id") == subject.get("id") or row.get("source_key") == subject.get("source_key"):
            continue
        if (row.get("status") or "").strip().lower() not in SOLD_STATUSES:
            continue
        sold_price = _float(row.get("result_price"))
        if not sold_price:
            continue
        if _commercial_family(row.get("property_type") or "") != subject_family:
            continue
        sold_date = _sale_date_for_row(row)
        if not sold_date or sold_date < since:
            continue
        size = extract_size_sqft(" ".join(str(row.get(k) or "") for k in ("title", "raw_text", "detail_text")))
        if subject_size and size:
            ratio = max(size / subject_size, subject_size / size)
            if ratio > config.commercial_max_size_ratio:
                continue
        lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
        distance = None
        if subject_lat is not None and subject_lon is not None and lat is not None and lon is not None:
            distance = haversine_miles(subject_lat, subject_lon, lat, lon)
            if distance > config.commercial_max_distance_miles:
                continue
        psf = sold_price / size if size else None
        months = _months_between(sold_date, today)
        size_match = 1.0
        if subject_size and size:
            ratio = min(size, subject_size) / max(size, subject_size)
            size_match = 0.55 + 0.45 * ratio
        distance_weight = 1.0 if distance is None or distance <= 5 else 0.82 if distance <= 15 else 0.62 if distance <= 30 else 0.45
        recency_weight = 1.0 if months <= 6 else 0.9 if months <= 12 else 0.78 if months <= 24 else 0.65
        match = size_match * distance_weight * recency_weight
        comps.append({
            "provider": "Tracked auction results",
            "source_ref": row.get("url") or row.get("source_key"),
            "address": row.get("address") or row.get("title") or "",
            "postcode": row.get("postcode") or "",
            "sale_price": int(round(sold_price)),
            "sale_date": sold_date.isoformat(),
            "property_type": row.get("property_type") or "Commercial",
            "tenure": "Unknown",
            "distance_miles": round(distance, 2) if distance is not None else None,
            "size_sqft": size,
            "price_per_sqft": round(psf, 2) if psf else None,
            "match_score": round(match * 100, 1),
            "same_property": 0,
            "metadata": {"auction_house": row.get("source"), "status": row.get("status")},
        })
    comps.sort(key=lambda c: c.get("match_score") or 0, reverse=True)
    comps = comps[: config.max_comps]

    psf_comps = [c for c in comps if c.get("price_per_sqft")]
    weighted_psf = [(float(c["price_per_sqft"]), max(0.01, float(c.get("match_score") or 1) / 100)) for c in psf_comps]
    psf_mid = _weighted_quantile(weighted_psf, 0.50)
    psf_low = _weighted_quantile(weighted_psf, 0.25)
    psf_high = _weighted_quantile(weighted_psf, 0.75)
    value_mid = psf_mid * subject_size if psf_mid and subject_size else None
    value_low = psf_low * subject_size if psf_low and subject_size else None
    value_high = psf_high * subject_size if psf_high and subject_size else None
    n = len(psf_comps)
    confidence = 12 + min(36, n * 7)
    if subject_size:
        confidence += 10
    if n >= 5:
        confidence += 8
    confidence = int(max(0, min(72, confidence)))
    guide = _float(subject.get("guide_price"))
    discount = ((value_mid - guide) / value_mid * 100) if value_mid and guide else None
    warnings = [
        "Commercial evidence is based on sold results captured from the tracked auction houses. Auction-sale evidence can reflect distress, special conditions or non-market circumstances and should not be treated as open-market RICS valuation evidence."
    ]
    if not subject_size:
        warnings.append("Subject floor area is missing, so sold £/sq ft evidence cannot yet be converted into an automated value range.")
    if n < 3:
        warnings.append("Fewer than three size-usable commercial auction comparables are available in the tracker database.")
    return {
        "provider": "Tracked auction results",
        "methodology": "Recent sold auction lots matched by commercial family, distance, size similarity and recency.",
        "valuation_low": _money_round(value_low, 5000),
        "valuation_mid": _money_round(value_mid, 5000),
        "valuation_high": _money_round(value_high, 5000),
        "unit_psf_low": round(psf_low, 2) if psf_low else None,
        "unit_psf_mid": round(psf_mid, 2) if psf_mid else None,
        "unit_psf_high": round(psf_high, 2) if psf_high else None,
        "comp_count": len(comps),
        "usable_psf_comp_count": n,
        "confidence": confidence,
        "guide_discount_pct": round(discount, 1) if discount is not None else None,
        "warnings": warnings,
        "attribution": "Sold auction evidence captured from the four tracked auction houses; source links retained per comparable.",
        "comps": comps,
    }


def refresh_property_comparables(db, subject: dict, session: requests.Session | None = None, config: ComparableConfig | None = None) -> dict:
    config = config or ComparableConfig()
    typ = (subject.get("property_type") or "").strip().lower()
    try:
        if typ in COMMERCIAL_TYPES:
            summary = internal_auction_comparables(db, subject, config=config)
        else:
            summary = LandRegistryPPDProvider(session=session, config=config).fetch(subject)
        db.save_comparable_bundle(subject["id"], summary, summary.pop("comps", []))
        return {"status": "ok", **summary}
    except Exception as exc:
        db.record_comparable_error(subject["id"], str(exc)[:800])
        return {"status": "error", "error": str(exc), "provider": "Tracked auction results" if typ in COMMERCIAL_TYPES else "HM Land Registry PPD"}


def refresh_due_comparables(db, rows: list[dict] | None = None, max_properties: int = 20, max_age_days: int = 14, session: requests.Session | None = None) -> dict:
    rows = rows or db.list_properties()
    candidates = [
        r for r in rows
        if (r.get("status") or "").strip().lower() not in SOLD_STATUSES
        and r.get("postcode")
        and db.comparables_due(r["id"], max_age_days=max_age_days)
    ]
    # Unsold / failed lots first, then newest rows. This puts seller-motivation opportunities at the front of the enrichment queue.
    status_priority = {"available post-auction": 0, "no bids": 1, "last bid": 2, "relisted": 3, "live": 4}
    candidates.sort(key=lambda r: (status_priority.get((r.get("status") or "").lower(), 5), -(r.get("id") or 0)))
    results = []
    shared_session = session or requests.Session()
    for row in candidates[: max(0, int(max_properties))]:
        results.append(refresh_property_comparables(db, row, session=shared_session))
    return {
        "due": len(candidates),
        "attempted": len(results),
        "ok": sum(r.get("status") == "ok" for r in results),
        "errors": [r.get("error") for r in results if r.get("status") == "error" and r.get("error")],
    }
