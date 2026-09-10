"""Planning intelligence for auction properties in England.

Uses the official MHCLG Planning Data API. The service is still beta and planning
application coverage varies by local planning authority, so absence of data is never
interpreted as confirmation that no planning constraints/applications exist.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable

import requests

PLANNING_API = "https://www.planning.data.gov.uk/entity.json"
PLANNING_ATTRIBUTION = "Planning Data (MHCLG), Open Government Licence v3.0; underlying datasets retain their stated attributions."

CONSTRAINT_DATASETS = [
    "conservation-area",
    "listed-building",
    "listed-building-outline",
    "flood-risk-zone",
    "green-belt",
    "article-4-direction-area",
    "tree-preservation-zone",
    "scheduled-monument",
    "site-of-special-scientific-interest",
    "ancient-woodland",
    "heritage-at-risk",
]

SEVERITY = {
    "listed-building": 4,
    "listed-building-outline": 3,
    "scheduled-monument": 5,
    "heritage-at-risk": 4,
    "conservation-area": 2,
    "article-4-direction-area": 3,
    "green-belt": 4,
    "tree-preservation-zone": 2,
    "site-of-special-scientific-interest": 5,
    "ancient-woodland": 4,
    "flood-risk-zone": 2,
}

CONSTRAINT_LABEL = {
    "listed-building": "Listed building",
    "listed-building-outline": "Listed-building extent",
    "scheduled-monument": "Scheduled monument",
    "heritage-at-risk": "Heritage at risk",
    "conservation-area": "Conservation area",
    "article-4-direction-area": "Article 4 direction",
    "green-belt": "Green belt",
    "tree-preservation-zone": "Tree preservation zone",
    "site-of-special-scientific-interest": "SSSI",
    "ancient-woodland": "Ancient woodland",
    "flood-risk-zone": "Flood-risk zone",
}

OPPORTUNITY_TERMS = re.compile(
    r"change of use|conversion|convert|dwelling|apartments?|flats?|residential|redevelop|"
    r"development|demolition|extension|warehouse|industrial|commercial|hmo|multiple occupation",
    re.I,
)


def _session(session=None):
    s = session or requests.Session()
    s.headers.update({"User-Agent": "NW-Auction-Deal-Finder/1.5 planning due-diligence", "Accept": "application/json"})
    return s


def _entities(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("entities")
    return rows if isinstance(rows, list) else []


def _parse_point(value: str | None):
    m = re.search(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", value or "", re.I)
    if not m:
        return None
    return float(m.group(2)), float(m.group(1))


def _haversine(lat1, lon1, lat2, lon2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bbox_wkt(lat: float, lon: float, radius_m: int = 350) -> str:
    radius_m = max(50, min(2000, int(radius_m)))
    dlat = radius_m / 111_320.0
    coslat = max(0.2, math.cos(math.radians(lat)))
    dlon = radius_m / (111_320.0 * coslat)
    west, east = lon - dlon, lon + dlon
    south, north = lat - dlat, lat + dlat
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def fetch_constraints(lat: float, lon: float, session=None) -> list[dict]:
    s = _session(session)
    params = [("latitude", lat), ("longitude", lon), ("limit", 100)]
    params += [("dataset", d) for d in CONSTRAINT_DATASETS]
    r = s.get(PLANNING_API, params=params, timeout=25)
    r.raise_for_status()
    return _entities(r.json())


def fetch_applications(lat: float, lon: float, session=None, radius_m: int = 350, years: int = 10) -> list[dict]:
    s = _session(session)
    year = max(2000, datetime.now(timezone.utc).year - int(years))
    params = [
        ("dataset", "planning-application"),
        ("geometry", _bbox_wkt(lat, lon, radius_m)),
        ("geometry_relation", "intersects"),
        ("start_date_year", year),
        ("start_date_month", 1),
        ("start_date_day", 1),
        ("start_date_match", "since"),
        ("limit", 100),
    ]
    r = s.get(PLANNING_API, params=params, timeout=25)
    r.raise_for_status()
    return _entities(r.json())


def _flood_severity(entity: dict) -> int:
    text = " ".join(str(entity.get(k) or "") for k in ("name", "reference", "description")).lower()
    if re.search(r"(?:zone\s*3|/3\b|\b3b\b|high)", text):
        return 5
    if re.search(r"(?:zone\s*2|/2\b|medium)", text):
        return 3
    return 2


def summarise_constraints(entities: Iterable[dict]) -> tuple[list[dict], float]:
    out = []
    seen = set()
    risk_by_family = {}
    for entity in entities or []:
        dataset = str(entity.get("dataset") or "")
        if dataset not in SEVERITY:
            continue
        ref = str(entity.get("reference") or entity.get("entity") or "")
        key = (dataset, ref)
        if key in seen:
            continue
        seen.add(key)
        severity = _flood_severity(entity) if dataset == "flood-risk-zone" else SEVERITY[dataset]
        family = "listed-building" if dataset in {"listed-building", "listed-building-outline"} else dataset
        risk_by_family[family] = max(risk_by_family.get(family, 0), severity)
        name = str(entity.get("name") or "").strip()
        label = CONSTRAINT_LABEL.get(dataset, dataset.replace("-", " ").title())
        detail = f"{label}: {name}" if name else label
        if ref:
            detail += f" ({ref})"
        out.append({
            "kind": "constraint",
            "dataset": dataset,
            "reference": ref,
            "name": name,
            "severity": severity,
            "label": detail,
            "source_url": f"https://www.planning.data.gov.uk/entity/{entity.get('entity')}" if entity.get("entity") else "https://www.planning.data.gov.uk/",
            "metadata": entity,
        })
    # One designation does not automatically kill a deal. The score represents DD burden.
    risk = round(min(10.0, sum(risk_by_family.values()) / 2.2), 1)
    return out, risk


def summarise_applications(entities: Iterable[dict], lat: float, lon: float, subject_postcode: str = "", subject_address: str = "") -> tuple[list[dict], float]:
    apps = []
    subject_opportunity = 0.0
    nearby_opportunity = 0.0
    subject_postcode = " ".join((subject_postcode or "").upper().split())
    subject_address = (subject_address or "").upper()
    subject_number_match = re.search(r"\b(\d+[A-Z]?)\b", subject_address)
    subject_number = subject_number_match.group(1) if subject_number_match else ""
    for entity in entities or []:
        point = _parse_point(entity.get("point"))
        distance = _haversine(lat, lon, point[0], point[1]) if point else None
        address = str(entity.get("address-text") or entity.get("name") or "").strip()
        description = str(entity.get("description") or "").strip()
        decision = str(entity.get("planning-decision") or "").strip()
        doc_url = str(entity.get("documentation-url") or "").strip()
        ref = str(entity.get("reference") or entity.get("entity") or "")
        same_postcode = bool(subject_postcode and subject_postcode in address.upper())
        app_number_match = re.search(r"\b(\d+[A-Z]?)\b", address.upper())
        app_number = app_number_match.group(1) if app_number_match else ""
        number_match = bool(subject_number and app_number and subject_number == app_number)
        likely_subject = (same_postcode and number_match) or (distance is not None and distance <= 0.02)
        approved = bool(re.search(r"approve|grant|permitted", decision, re.I))
        opportunity_terms = bool(OPPORTUNITY_TERMS.search(description))
        if likely_subject and approved and opportunity_terms:
            subject_opportunity += 3.0
        elif distance is not None and distance <= 0.15 and approved and opportunity_terms:
            nearby_opportunity += 0.7
        apps.append({
            "kind": "application",
            "dataset": "planning-application",
            "reference": ref,
            "name": address,
            "severity": 0,
            "label": f"{ref} - {description[:180]}",
            "source_url": doc_url or (f"https://www.planning.data.gov.uk/entity/{entity.get('entity')}" if entity.get("entity") else ""),
            "distance_miles": round(distance, 3) if distance is not None else None,
            "likely_subject": likely_subject,
            "metadata": entity,
        })
    apps.sort(key=lambda x: (0 if x.get("likely_subject") else 1, x.get("distance_miles") if x.get("distance_miles") is not None else 999, x.get("metadata", {}).get("start-date", "")), reverse=False)
    opportunity = min(10.0, subject_opportunity + min(3.0, nearby_opportunity))
    return apps[:40], round(opportunity, 1)


def analyse_planning_property(lot: dict, session=None, radius_m: int = 350) -> tuple[dict, list[dict]]:
    lat, lon = lot.get("latitude"), lot.get("longitude")
    if lat is None or lon is None:
        return ({
            "provider": "Planning Data (MHCLG)", "status": "unavailable", "risk_score": 0.0,
            "opportunity_score": 0.0, "constraint_count": 0, "application_count": 0,
            "methodology": "Coordinates required before official spatial planning checks can run.",
            "warnings": ["Property has not been geocoded yet."], "attribution": PLANNING_ATTRIBUTION,
        }, [])
    warnings = [
        "Planning Data is a beta service and coverage varies by local planning authority. No result does not prove no constraint or application exists."
    ]
    constraints = fetch_constraints(float(lat), float(lon), session=session)
    applications = fetch_applications(float(lat), float(lon), session=session, radius_m=radius_m)
    constraint_items, risk = summarise_constraints(constraints)
    app_items, upside = summarise_applications(applications, float(lat), float(lon), lot.get("postcode") or "", lot.get("address") or lot.get("title") or "")
    subject_apps = sum(1 for x in app_items if x.get("likely_subject"))
    summary = {
        "provider": "Planning Data (MHCLG)",
        "status": "ok",
        "risk_score": risk,
        "opportunity_score": upside,
        "constraint_count": len(constraint_items),
        "application_count": len(app_items),
        "subject_application_count": subject_apps,
        "methodology": f"Official spatial constraints at the geocoded point plus planning applications within approximately {radius_m}m over the last 10 years.",
        "warnings": warnings,
        "attribution": PLANNING_ATTRIBUTION,
    }
    return summary, constraint_items + app_items
