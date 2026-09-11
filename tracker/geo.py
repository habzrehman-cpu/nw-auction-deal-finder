"""Geocoding and motorway-junction distance enrichment.

Coordinates are obtained from Postcodes.io. Motorway junction nodes are sourced from
OpenStreetMap through Overpass and cached locally. For a property with coordinates,
the nearest few motorway junctions are identified geodesically, then OSRM is used to
attempt a road distance. When OSRM is unavailable, straight-line distance is retained
and labelled as such.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

TARGET_MOTORWAYS = {
    "M6", "M53", "M55", "M56", "M57", "M58", "M60", "M61", "M62",
    "M65", "M66", "M67", "M602",
}
NW_BBOX = (52.80, -3.85, 55.25, -1.55)  # south, west, north, east
POSTCODES_URL = "https://api.postcodes.io/postcodes?filter=postcode,longitude,latitude"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
OSRM_BASE = "https://router.project-osrm.org"


def _utcnow():
    return datetime.now(timezone.utc)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return r_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def _normalise_motorway_ref(value: str) -> list[str]:
    text = (value or "").upper().replace(" ", "")
    return [m for m in TARGET_MOTORWAYS if re.search(rf"(?<![A-Z0-9]){re.escape(m)}(?![A-Z0-9])", text)]


def bulk_geocode(postcodes: Iterable[str], session: requests.Session | None = None, timeout=20) -> dict[str, dict]:
    unique = []
    seen = set()
    for p in postcodes:
        p = " ".join((p or "").upper().split())
        if p and p not in seen:
            seen.add(p); unique.append(p)
    if not unique:
        return {}
    s = session or requests.Session()
    out: dict[str, dict] = {}
    for start in range(0, len(unique), 100):
        batch = unique[start:start + 100]
        r = s.post(POSTCODES_URL, json={"postcodes": batch}, timeout=timeout)
        r.raise_for_status()
        payload = r.json()
        for item in payload.get("result") or []:
            query = " ".join((item.get("query") or "").upper().split())
            result = item.get("result") or {}
            if result.get("latitude") is None or result.get("longitude") is None:
                continue
            out[query] = {
                "postcode": result.get("postcode") or query,
                "latitude": float(result["latitude"]),
                "longitude": float(result["longitude"]),
                "source": "Postcodes.io",
            }
    return out


class MotorwayNetwork:
    def __init__(self, cache_path: str | Path | None = None, session: requests.Session | None = None, timeout=35):
        self.cache_path = Path(cache_path) if cache_path else Path(__file__).with_name("motorway_junctions_cache.json")
        self.session = session or requests.Session()
        headers = getattr(self.session, "headers", None)
        if headers is not None:
            headers.update({"User-Agent": "NW-Auction-Deal-Finder/1.6 contact: browser-app"})
        self.timeout = timeout

    def load(self, max_age_days=30) -> list[dict]:
        cached = self._read_cache(max_age_days)
        if cached is not None:
            return cached
        junctions = self.fetch()
        if junctions:
            self._write_cache(junctions)
        return junctions

    def _read_cache(self, max_age_days: int):
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(payload.get("updated_at", "").replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if _utcnow() - stamp > timedelta(days=max_age_days):
                return None
            return payload.get("junctions") or []
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return None

    def _write_cache(self, junctions: list[dict]):
        payload = {"updated_at": _utcnow().isoformat(), "junctions": junctions}
        try:
            self.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def fetch(self) -> list[dict]:
        south, west, north, east = NW_BBOX
        motorway_regex = "^(?:" + "|".join(sorted(TARGET_MOTORWAYS, key=len, reverse=True)) + ")$"
        query = f"""
[out:json][timeout:30];
way[\"highway\"=\"motorway\"][\"ref\"~\"{motorway_regex}\"]({south},{west},{north},{east})->.motorways;
node(w.motorways)[\"highway\"=\"motorway_junction\"]->.junctions;
(.motorways;.junctions;);
out body;
"""
        last_error = None
        elements = []
        for endpoint in OVERPASS_URLS:
            try:
                r = self.session.post(endpoint, data={"data": query}, timeout=self.timeout)
                r.raise_for_status()
                elements = (r.json() or {}).get("elements") or []
                if elements:
                    break
            except Exception as exc:
                last_error = exc
                continue

        ways = [e for e in elements if e.get("type") == "way"]
        nodes = {e.get("id"): e for e in elements if e.get("type") == "node"}
        memberships: dict[int, set[str]] = {}
        for way in ways:
            refs = _normalise_motorway_ref((way.get("tags") or {}).get("ref", ""))
            if not refs:
                continue
            for node_id in way.get("nodes") or []:
                if node_id in nodes:
                    memberships.setdefault(node_id, set()).update(refs)

        junctions = []
        for node_id, node in nodes.items():
            refs = sorted(memberships.get(node_id) or [])
            if not refs:
                continue
            tags = node.get("tags") or {}
            jref = str(tags.get("ref") or tags.get("junction:ref") or "").strip()
            jref = re.sub(r"^J(?:unction)?\s*", "", jref, flags=re.I)
            motorway = "/".join(refs)
            label = f"{motorway} J{jref}" if jref else (tags.get("name") or f"{motorway} junction")
            junctions.append({
                "osm_id": node_id, "motorway": motorway, "junction_ref": jref, "label": label,
                "latitude": float(node["lat"]), "longitude": float(node["lon"]),
            })
        if junctions:
            return junctions

        # Some public Overpass instances do not return parent-way membership reliably.
        # Fall back to motorway_junction nodes so distance still works, even if the
        # motorway name is not present in the node tags.
        fallback_query = f"""
[out:json][timeout:25];
node[\"highway\"=\"motorway_junction\"]({south},{west},{north},{east});
out body;
"""
        for endpoint in OVERPASS_URLS:
            try:
                r = self.session.post(endpoint, data={"data": fallback_query}, timeout=self.timeout)
                r.raise_for_status()
                raw = (r.json() or {}).get("elements") or []
                fallback = []
                for node in raw:
                    if node.get("type") != "node" or node.get("lat") is None or node.get("lon") is None:
                        continue
                    tags = node.get("tags") or {}
                    probe = " ".join(str(v) for v in tags.values())
                    refs = sorted(_normalise_motorway_ref(probe))
                    motorway = "/".join(refs) if refs else "Motorway"
                    jref = str(tags.get("ref") or tags.get("junction:ref") or "").strip()
                    jref = re.sub(r"^J(?:unction)?\s*", "", jref, flags=re.I)
                    label = tags.get("name") or (f"{motorway} J{jref}" if jref else "Motorway junction")
                    fallback.append({
                        "osm_id": node.get("id"), "motorway": motorway, "junction_ref": jref, "label": label,
                        "latitude": float(node["lat"]), "longitude": float(node["lon"]),
                    })
                if fallback:
                    return fallback
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise RuntimeError(f"OpenStreetMap motorway junction lookup failed: {last_error}")
        return []


def nearest_candidates(latitude: float, longitude: float, junctions: list[dict], limit=4) -> list[dict]:
    ranked = []
    for j in junctions:
        air = haversine_miles(latitude, longitude, float(j["latitude"]), float(j["longitude"]))
        ranked.append({**j, "air_miles": round(air, 2)})
    ranked.sort(key=lambda x: x["air_miles"])
    return ranked[:max(1, limit)]


def _road_distances(latitude: float, longitude: float, candidates: list[dict], session=None, timeout=12):
    if not candidates:
        return []
    s = session or requests.Session()
    coords = [f"{longitude:.6f},{latitude:.6f}"] + [f"{c['longitude']:.6f},{c['latitude']:.6f}" for c in candidates]
    dests = ";".join(str(i) for i in range(1, len(coords)))
    url = f"{OSRM_BASE}/table/v1/driving/{';'.join(coords)}"
    r = s.get(url, params={"sources": "0", "destinations": dests, "annotations": "distance"}, timeout=timeout)
    r.raise_for_status()
    distances = ((r.json() or {}).get("distances") or [[]])[0]
    result = []
    for c, metres in zip(candidates, distances):
        if metres is None:
            continue
        result.append({**c, "road_miles": round(float(metres) / 1609.344, 2)})
    return result


def nearest_motorway(latitude: float, longitude: float, junctions: list[dict], session=None, road=True) -> dict | None:
    candidates = nearest_candidates(latitude, longitude, junctions, limit=4)
    if not candidates:
        return None
    if road:
        try:
            routed = _road_distances(latitude, longitude, candidates, session=session)
            if routed:
                best = min(routed, key=lambda x: x["road_miles"])
                return {
                    "nearest_motorway": best["motorway"],
                    "nearest_junction": best["label"],
                    "motorway_air_miles": best["air_miles"],
                    "motorway_road_miles": best["road_miles"],
                    "motorway_distance_kind": "road",
                }
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass
    best = candidates[0]
    return {
        "nearest_motorway": best["motorway"],
        "nearest_junction": best["label"],
        "motorway_air_miles": best["air_miles"],
        "motorway_road_miles": None,
        "motorway_distance_kind": "straight-line",
    }
