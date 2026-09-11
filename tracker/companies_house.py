"""Companies House enrichment for corporate auction sellers.

The integration is optional and read-only. It uses the official Companies House
Public Data API when an API key is configured. The tracker stores only corporate
facts useful to acquisition due diligence (company status, registered office,
active directors, charges, insolvency, PSCs and recent filings). It deliberately
avoids surfacing dates of birth or personal residential addresses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import re
from typing import Any

import requests

BASE_URL = "https://api.company-information.service.gov.uk"
PUBLIC_COMPANY_URL = "https://find-and-update.company-information.service.gov.uk/company/{company_number}"
PROVIDER = "Companies House Public Data API"

DISTRESS_STATUSES = {
    "liquidation",
    "receivership",
    "administration",
    "voluntary-arrangement",
    "insolvency-proceedings",
}


def _clean(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _normalise_company_number(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:10]


def _normalise_company_name(value: str | None) -> str:
    text = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    for suffix in (" LIMITED", " LTD", " PLC", " LLP"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text


def _address_line(address: dict | None) -> str:
    address = address or {}
    parts = [
        address.get("premises"), address.get("address_line_1"), address.get("address_line_2"),
        address.get("locality"), address.get("region"), address.get("postal_code"), address.get("country"),
    ]
    return ", ".join(_clean(x, 90) for x in parts if _clean(x, 90))


def _safe_date(value: Any) -> str | None:
    text = _clean(value, 32)
    if not text:
        return None
    return text[:10]


@dataclass
class CompaniesHouseConfig:
    api_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(str(self.api_key or "").strip())


class CompaniesHouseClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 18):
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("Companies House API key is not configured")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "NW-Auction-Deal-Finder/1.9"})
        self.timeout = timeout

    def _get(self, path: str, params: dict | None = None, allow_404: bool = False) -> dict:
        url = f"{BASE_URL}{path}"
        r = self.session.get(url, params=params or {}, auth=(self.api_key, ""), timeout=self.timeout)
        if allow_404 and r.status_code == 404:
            return {}
        if r.status_code == 429:
            raise RuntimeError("Companies House rate limit reached; retry later")
        r.raise_for_status()
        payload = r.json()
        return payload if isinstance(payload, dict) else {}

    def search_companies(self, query: str, items_per_page: int = 10) -> list[dict]:
        payload = self._get("/search/companies", {"q": query, "items_per_page": max(1, min(20, items_per_page))})
        return list(payload.get("items") or [])

    def profile(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}")

    def officers(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}/officers", {"items_per_page": 50})

    def charges(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}/charges", {"items_per_page": 100}, allow_404=True)

    def insolvency(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}/insolvency", allow_404=True)

    def psc(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}/persons-with-significant-control", {"items_per_page": 50}, allow_404=True)

    def filings(self, company_number: str, items_per_page: int = 20) -> dict:
        number = _normalise_company_number(company_number)
        return self._get(f"/company/{number}/filing-history", {"items_per_page": max(1, min(100, items_per_page))}, allow_404=True)

    def resolve_company(self, seller_name: str, registered_office: str = "") -> dict:
        """Resolve a company only where the evidence is strong enough to avoid guessing.

        Exact unique name matches are accepted. Where there are multiple exact-name
        matches, a registered-office postcode can disambiguate. Otherwise candidates
        are returned and the caller should leave the company unresolved.
        """
        query = _clean(seller_name, 180)
        if not query:
            return {"resolved": False, "reason": "seller-name-missing", "candidates": []}
        items = self.search_companies(query)
        target = _normalise_company_name(query)
        exact = [x for x in items if _normalise_company_name(x.get("title")) == target]
        office_postcode = ""
        m = re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", str(registered_office or "").upper())
        if m:
            office_postcode = "".join(m.group(0).split())
        chosen = None
        confidence = None
        if len(exact) == 1:
            chosen = exact[0]
            confidence = "exact-name"
        elif office_postcode and exact:
            postcode_matches = []
            for item in exact:
                address = item.get("address") or {}
                candidate_pc = "".join(str(address.get("postal_code") or "").upper().split())
                if candidate_pc and candidate_pc == office_postcode:
                    postcode_matches.append(item)
            if len(postcode_matches) == 1:
                chosen = postcode_matches[0]
                confidence = "exact-name-and-postcode"
        return {
            "resolved": bool(chosen),
            "company_number": _normalise_company_number(chosen.get("company_number")) if chosen else None,
            "company_name": _clean(chosen.get("title"), 180) if chosen else None,
            "confidence": confidence,
            "reason": "resolved" if chosen else ("ambiguous" if exact else "no-exact-match"),
            "candidates": [
                {
                    "company_number": _normalise_company_number(x.get("company_number")),
                    "company_name": _clean(x.get("title"), 180),
                    "company_status": _clean(x.get("company_status"), 60),
                    "registered_office": _address_line(x.get("address") or {}),
                }
                for x in exact[:6]
            ],
        }

    def fetch_bundle(self, company_number: str) -> dict:
        number = _normalise_company_number(company_number)
        if not number:
            raise ValueError("Company number is required")
        profile = self.profile(number)
        officers = self.officers(number)
        charges = self.charges(number)
        insolvency = self.insolvency(number)
        psc = self.psc(number)
        filings = self.filings(number)
        return build_company_intelligence(number, profile, officers, charges, insolvency, psc, filings)


def _active_directors(officers_payload: dict) -> list[dict]:
    out = []
    for item in officers_payload.get("items") or []:
        if item.get("resigned_on"):
            continue
        role = _clean(item.get("officer_role"), 80)
        if role not in {"director", "corporate-director", "llp-member", "corporate-llp-member"}:
            continue
        out.append({
            "name": _clean(item.get("name"), 180),
            "role": role,
            "appointed_on": _safe_date(item.get("appointed_on")),
        })
    return out[:20]


def _psc_rows(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("items") or []:
        name = item.get("name") or item.get("name_elements", {}).get("surname") or item.get("description")
        out.append({
            "name": _clean(name, 180),
            "kind": _clean(item.get("kind"), 90),
            "ceased_on": _safe_date(item.get("ceased_on")),
            "natures_of_control": [_clean(x, 120) for x in (item.get("natures_of_control") or [])[:8]],
        })
    return out[:20]


def _charge_rows(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("items") or []:
        classification = item.get("classification") or {}
        persons = []
        for p in item.get("persons_entitled") or []:
            name = _clean(p.get("name"), 180)
            if name:
                persons.append(name)
        out.append({
            "status": _clean(item.get("status"), 60) or "unknown",
            "created_on": _safe_date(item.get("created_on")),
            "delivered_on": _safe_date(item.get("delivered_on")),
            "satisfied_on": _safe_date(item.get("satisfied_on")),
            "classification": _clean(classification.get("description") or classification.get("type"), 180),
            "persons_entitled": persons[:6],
        })
    return out[:80]


def _insolvency_rows(payload: dict) -> list[dict]:
    out = []
    for case in payload.get("cases") or []:
        dates = []
        for d in case.get("dates") or []:
            dates.append({"date": _safe_date(d.get("date")), "type": _clean(d.get("type"), 100)})
        out.append({
            "type": _clean(case.get("type"), 120),
            "number": _clean(case.get("number"), 60),
            "dates": dates[:12],
        })
    return out[:20]


def _filing_rows(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("items") or []:
        out.append({
            "date": _safe_date(item.get("date")),
            "category": _clean(item.get("category"), 80),
            "description": _clean(item.get("description"), 150),
            "type": _clean(item.get("type"), 60),
            "action_date": _safe_date(item.get("action_date")),
        })
    return out[:25]


def build_company_intelligence(company_number: str, profile: dict, officers: dict, charges: dict,
                               insolvency: dict, psc: dict, filings: dict) -> dict:
    number = _normalise_company_number(company_number)
    company_status = _clean(profile.get("company_status"), 80)
    accounts = profile.get("accounts") or {}
    confirmation = profile.get("confirmation_statement") or {}
    active_directors = _active_directors(officers)
    charge_rows = _charge_rows(charges)
    insolvency_rows = _insolvency_rows(insolvency)
    psc_rows = _psc_rows(psc)
    filing_rows = _filing_rows(filings)
    outstanding = [x for x in charge_rows if str(x.get("status") or "").lower() not in {"fully-satisfied", "satisfied"}]
    satisfied = [x for x in charge_rows if str(x.get("status") or "").lower() in {"fully-satisfied", "satisfied"}]
    pressure_reasons = []
    pressure_points = 0
    low_status = company_status.lower()
    if low_status in DISTRESS_STATUSES:
        pressure_points += 70
        pressure_reasons.append(f"Companies House status is {company_status}")
    elif "proposal-to-strike-off" in _clean(profile.get("company_status_detail"), 120).lower():
        pressure_points += 35
        pressure_reasons.append("Companies House shows an active proposal to strike off")
    elif company_status and company_status.lower() != "active":
        pressure_points += 30
        pressure_reasons.append(f"Company status is {company_status}")
    if insolvency_rows:
        pressure_points += min(25, 10 + 5 * len(insolvency_rows))
        pressure_reasons.append(f"{len(insolvency_rows)} insolvency case(s) are recorded")
    if bool(accounts.get("overdue") or (accounts.get("next_accounts") or {}).get("overdue")):
        pressure_points += 10
        pressure_reasons.append("Accounts filing is shown as overdue")
    if bool(confirmation.get("overdue")):
        pressure_points += 5
        pressure_reasons.append("Confirmation statement is shown as overdue")
    # Charges are factual financing evidence but are not treated as distress on their own.
    if outstanding:
        pressure_reasons.append(f"{len(outstanding)} outstanding/unsatisfied charge(s) are recorded (not distress proof by itself)")
    pressure_score = round(min(100, pressure_points) / 10, 1)
    pressure_label = "Very High" if pressure_score >= 8.5 else "High" if pressure_score >= 7 else "Medium" if pressure_score >= 5 else "Low" if pressure_score >= 3 else "Very Low"
    return {
        "provider": PROVIDER,
        "status": "ok",
        "company_number": number,
        "company_name": _clean(profile.get("company_name"), 180),
        "company_status": company_status,
        "company_status_detail": _clean(profile.get("company_status_detail"), 160),
        "company_type": _clean(profile.get("type"), 100),
        "incorporation_date": _safe_date(profile.get("date_of_creation")),
        "registered_office": _address_line(profile.get("registered_office_address") or {}),
        "sic_codes": [_clean(x, 16) for x in (profile.get("sic_codes") or [])[:8]],
        "accounts_overdue": bool(accounts.get("overdue") or (accounts.get("next_accounts") or {}).get("overdue")),
        "accounts_next_due": _safe_date(accounts.get("next_due") or (accounts.get("next_accounts") or {}).get("due_on")),
        "confirmation_overdue": bool(confirmation.get("overdue")),
        "confirmation_next_due": _safe_date(confirmation.get("next_due")),
        "active_directors": active_directors,
        "persons_with_significant_control": psc_rows,
        "charges": charge_rows,
        "outstanding_charge_count": len(outstanding),
        "satisfied_charge_count": len(satisfied),
        "insolvency_cases": insolvency_rows,
        "insolvency_case_count": len(insolvency_rows),
        "recent_filings": filing_rows,
        "corporate_pressure_score": pressure_score,
        "corporate_pressure_label": pressure_label,
        "corporate_pressure_reasons": pressure_reasons,
        "company_url": PUBLIC_COMPANY_URL.format(company_number=number),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": (
            "Read-only Companies House public-data enrichment. Corporate status, insolvency and filing facts are source evidence. "
            "The corporate-pressure score is acquisition triage only and does not prove financial distress or seller intent."
        ),
    }


def company_due(summary: dict | None, max_age_days: int = 7) -> bool:
    summary = summary or {}
    if not summary or summary.get("status") == "error" or not summary.get("updated_at"):
        return True
    try:
        stamp = datetime.fromisoformat(str(summary["updated_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - stamp > timedelta(days=max_age_days)
    except (TypeError, ValueError):
        return True
