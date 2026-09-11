"""Orchestration for planning and legal-pack due diligence."""
from __future__ import annotations

import requests
import re

from .legal import analyse_online_legal_pack, analyse_legal_documents, compare_legal_documents
from .legal_access import LegalAccessConfig
from .planning import analyse_planning_property
from .companies_house import CompaniesHouseClient, company_due

SOLD = {"sold", "sold prior", "sold after"}
PRIORITY_STATUS = {
    "available post-auction": 0,
    "no bids": 1,
    "last bid": 2,
    "relisted": 3,
    "live": 4,
}


def _priority(row):
    status = (row.get("status") or "").lower()
    typ = (row.get("property_type") or "").lower()
    commercial = typ in {"commercial", "industrial", "mixed use", "development", "land"}
    return (PRIORITY_STATUS.get(status, 8), 0 if commercial else 1, row.get("guide_price") or 10**12)


def refresh_property_planning(db, row, session=None):
    summary, items = analyse_planning_property(row, session=session)
    db.save_planning_bundle(row["id"], summary, items)
    return summary


def refresh_property_legal(db, row, session=None, legal_access: LegalAccessConfig | None = None, cloud_store=None):
    summary, online_docs = analyse_online_legal_pack(row, session=session, access_config=legal_access)
    # Retain automatically acquired originals in the private cloud when configured.
    for doc in online_docs:
        raw = doc.pop("_raw_bytes", b"")
        if raw and cloud_store:
            try:
                path = cloud_store.upload_legal_document(
                    row["id"], doc.get("name") or "legal-document", raw, doc.get("sha256") or "document"
                )
                doc.setdefault("metadata", {})["cloud_storage_path"] = path
                doc["access_status"] = (doc.get("access_status") or "downloaded") + " and stored privately"
            except Exception as exc:
                doc.setdefault("metadata", {})["cloud_storage_error"] = str(exc)[:300]
    existing = db.legal_documents_for(row["id"])
    uploaded = [d for d in existing if (d.get("metadata") or {}).get("origin") == "user-upload"]
    prior_online = [d for d in existing if (d.get("metadata") or {}).get("origin") != "user-upload"]
    # Keep user evidence when the online pack is refreshed. If automation is blocked
    # by provider permission/login controls, preserve previously discovered online
    # links rather than deleting the user's manual access route.
    if online_docs:
        combined = uploaded + online_docs
    else:
        combined = uploaded + prior_online
        if prior_online:
            blocked_warnings = summary.get("warnings") or []
            summary = analyse_legal_documents(combined, str(row.get("detail_text") or ""))
            summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + blocked_warnings + [
                "Previously discovered legal links were retained because the current automatic acquisition attempt did not return a replacement pack."
            ]))
    if uploaded:
        summary = analyse_legal_documents(combined, str(row.get("detail_text") or ""))
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "User-uploaded documents are included in this analysis alongside any public auctioneer documents."
        ]))
    change = compare_legal_documents(existing, combined)
    summary["pack_changed"] = bool(change.get("changed"))
    summary["pack_change"] = change
    if change.get("changed"):
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "Legal-pack evidence changed since the previous saved snapshot. Review added, removed or modified documents before bidding."
        ]))
    db.save_legal_bundle(row["id"], summary, combined)
    return summary


def save_uploaded_legal_documents(db, row, uploaded_docs):
    existing = db.legal_documents_for(row["id"])
    # Replace any prior upload with the same hash; preserve online documents.
    by_hash = {d.get("sha256"): d for d in existing if d.get("sha256")}
    for doc in uploaded_docs:
        by_hash[doc.get("sha256")] = doc
    no_hash = [d for d in existing if not d.get("sha256")]
    combined = no_hash + list(by_hash.values())
    summary = analyse_legal_documents(combined, str(row.get("detail_text") or ""))
    change = compare_legal_documents(existing, combined)
    summary["pack_changed"] = bool(change.get("changed"))
    summary["pack_change"] = change
    cloud_retained = any((d.get("metadata") or {}).get("cloud_storage_path") for d in uploaded_docs or [])
    retention_note = (
        "User-uploaded legal originals are retained in the configured private cloud storage and extracted text is stored with the deal."
        if cloud_retained else
        "User-uploaded evidence is stored as extracted text in the tracker database; original files are only retained across reboot when private cloud persistence is configured."
    )
    summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [retention_note]))
    db.save_legal_bundle(row["id"], summary, combined)
    return summary


def refresh_property_company(db, row, api_key: str, session=None):
    """Refresh Companies House intelligence for a property where corporate seller evidence exists."""
    legal = db.legal_summary_for(row["id"])
    extracted = legal.get("extracted_fields") or {}
    company_number = str(extracted.get("company_number") or "").strip()
    seller_name = str(extracted.get("seller_name") or extracted.get("proprietor_name") or "").strip()
    registered_office = str(extracted.get("registered_office") or "").strip()
    client = CompaniesHouseClient(api_key, session=session)
    resolution = None
    if not company_number and seller_name:
        resolution = client.resolve_company(seller_name, registered_office)
        if resolution.get("resolved"):
            company_number = resolution.get("company_number") or ""
    if not company_number:
        summary = {
            "provider": "Companies House Public Data API",
            "status": "unresolved",
            "company_number": None,
            "company_name": seller_name or None,
            "resolution": resolution or {},
            "error": "No definitive company number is available from the legal evidence.",
        }
        db.save_company_intelligence(row["id"], summary)
        return summary
    summary = client.fetch_bundle(company_number)
    if resolution:
        summary["resolution"] = resolution
    db.save_company_intelligence(row["id"], summary)
    return summary


def refresh_due_company_intelligence(db, api_key: str, rows=None, max_companies=12):
    """Refresh official corporate intelligence for priority lots with identified company sellers."""
    result = {"attempted": 0, "ok": 0, "unresolved": 0, "errors": []}
    if not str(api_key or "").strip():
        result["configured"] = False
        return result
    result["configured"] = True
    rows = list(rows or db.list_properties())
    candidates = []
    for row in rows:
        legal = db.legal_summary_for(row["id"])
        extracted = legal.get("extracted_fields") or {}
        seller_name = str(extracted.get("seller_name") or extracted.get("proprietor_name") or "")
        company_number = str(extracted.get("company_number") or "")
        companyish = bool(company_number) or bool(re.search(r"\b(?:LTD|LIMITED|PLC|LLP)\b", seller_name, re.I))
        if not companyish:
            continue
        existing = db.company_intelligence_for(row["id"])
        if company_due(existing):
            candidates.append(row)
    candidates.sort(key=_priority)
    session = requests.Session()
    for row in candidates[:max_companies]:
        result["attempted"] += 1
        try:
            summary = refresh_property_company(db, row, api_key, session=session)
            if summary.get("status") == "ok":
                result["ok"] += 1
            else:
                result["unresolved"] += 1
        except Exception as exc:
            legal = db.legal_summary_for(row["id"])
            number = (legal.get("extracted_fields") or {}).get("company_number")
            db.record_company_error(row["id"], exc, number)
            result["errors"].append(f"{row.get('postcode') or row.get('title')}: {exc}")
    return result


def refresh_due_diligence(db, rows=None, max_planning=20, max_legal=12, legal_access: LegalAccessConfig | None = None, cloud_store=None):
    rows = list(rows or db.list_properties())
    actionable = [r for r in rows if (r.get("status") or "").lower() not in SOLD]
    actionable.sort(key=_priority)
    session = requests.Session()
    result = {
        "planning_attempted": 0, "planning_ok": 0, "planning_errors": [],
        "legal_attempted": 0, "legal_ok": 0, "legal_errors": [],
    }
    for row in [x for x in actionable if db.planning_due(x["id"])][:max_planning]:
        result["planning_attempted"] += 1
        try:
            refresh_property_planning(db, row, session=session)
            result["planning_ok"] += 1
        except Exception as exc:
            db.record_planning_error(row["id"], exc)
            result["planning_errors"].append(f"{row.get('postcode') or row.get('title')}: {exc}")
    for row in [x for x in actionable if db.legal_due(x["id"])][:max_legal]:
        result["legal_attempted"] += 1
        try:
            refresh_property_legal(db, row, session=session, legal_access=legal_access, cloud_store=cloud_store)
            result["legal_ok"] += 1
        except Exception as exc:
            db.record_legal_error(row["id"], exc)
            result["legal_errors"].append(f"{row.get('postcode') or row.get('title')}: {exc}")
    return result
