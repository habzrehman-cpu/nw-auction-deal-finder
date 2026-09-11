"""Orchestration for planning and legal-pack due diligence."""
from __future__ import annotations

import requests

from .legal import analyse_online_legal_pack, analyse_legal_documents
from .planning import analyse_planning_property

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


def refresh_property_legal(db, row, session=None):
    summary, online_docs = analyse_online_legal_pack(row, session=session)
    existing = db.legal_documents_for(row["id"])
    uploaded = [d for d in existing if (d.get("metadata") or {}).get("origin") == "user-upload"]
    # Keep user evidence when the online pack is refreshed.
    combined = uploaded + online_docs
    if uploaded:
        summary = analyse_legal_documents(combined, str(row.get("detail_text") or ""))
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "User-uploaded documents are included in this analysis alongside any public auctioneer documents."
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
    cloud_retained = any((d.get("metadata") or {}).get("cloud_storage_path") for d in uploaded_docs or [])
    retention_note = (
        "User-uploaded legal originals are retained in the configured private cloud storage and extracted text is stored with the deal."
        if cloud_retained else
        "User-uploaded evidence is stored as extracted text in the tracker database; original files are only retained across reboot when private cloud persistence is configured."
    )
    summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [retention_note]))
    db.save_legal_bundle(row["id"], summary, combined)
    return summary


def refresh_due_diligence(db, rows=None, max_planning=20, max_legal=12):
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
            refresh_property_legal(db, row, session=session)
            result["legal_ok"] += 1
        except Exception as exc:
            db.record_legal_error(row["id"], exc)
            result["legal_errors"].append(f"{row.get('postcode') or row.get('title')}: {exc}")
    return result
