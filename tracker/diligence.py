"""Orchestration for planning and legal-pack due diligence."""
from __future__ import annotations

import requests
import re

from .legal import analyse_online_legal_pack, analyse_legal_documents, compare_legal_documents, revalidate_saved_legal_documents, uploaded_documents
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



def _reparse_stored_user_uploads(row, documents, cloud_store=None):
    """Re-run retained user-upload originals through the current parser when possible.

    Legal document classification/extraction improves over time.  A normal evidence
    refresh must therefore re-parse the *original bytes* rather than merely retaining
    the text/doc_type produced by an older release.  Originals are retrieved only
    from the configured private cloud path already attached to the saved evidence.
    If an original is unavailable we keep the existing evidence and report that the
    user may need to upload it again; we never silently discard it.
    """
    report = {"attempted": 0, "reprocessed": 0, "failed": 0, "notes": []}
    if not cloud_store:
        return list(documents or []), report

    rebuilt = []
    for original in list(documents or []):
        meta = original.get("metadata") or {}
        if str(meta.get("origin") or "") != "user-upload":
            rebuilt.append(original)
            continue
        storage_path = str(meta.get("cloud_storage_path") or "").strip()
        if not storage_path:
            rebuilt.append(original)
            continue

        report["attempted"] += 1
        try:
            raw = cloud_store.download_bytes(storage_path)
            if not raw:
                raise RuntimeError("stored original could not be retrieved")
            reparsed = uploaded_documents(original.get("name") or "stored legal document", raw)
            if not reparsed:
                raise RuntimeError("current parser returned no legal document")
            for doc in reparsed:
                doc.pop("_raw_bytes", None)
                new_meta = doc.setdefault("metadata", {})
                # Keep persistence/audit provenance from the original stored record.
                new_meta["cloud_storage_path"] = storage_path
                if meta.get("uploaded_container") and not new_meta.get("uploaded_container"):
                    new_meta["uploaded_container"] = meta.get("uploaded_container")
                new_meta["reprocessed_from_stored_original"] = True
                doc["access_status"] = (
                    "stored user upload re-analysed with the current legal parser"
                    if doc.get("text_content") else
                    "stored user upload re-analysed; no extractable text"
                )
                rebuilt.append(doc)
            report["reprocessed"] += 1
        except Exception as exc:
            report["failed"] += 1
            report["notes"].append(
                f"Could not re-analyse stored upload '{original.get('name') or 'document'}': {str(exc)[:220]}"
            )
            rebuilt.append(original)
    return rebuilt, report


def refresh_property_legal(db, row, session=None, legal_access: LegalAccessConfig | None = None, cloud_store=None):
    # Revalidate everything already stored *before* we merge in a fresh online
    # acquisition. This is the v1.10.3 purge step that prevents old bad evidence
    # from surviving a firewall upgrade merely because the provider is unavailable.
    existing_raw = db.legal_documents_for(row["id"])
    existing_reparsed, stored_reparse = _reparse_stored_user_uploads(row, existing_raw, cloud_store=cloud_store)
    existing, revalidation = revalidate_saved_legal_documents(row, existing_reparsed)

    online_summary, online_docs = analyse_online_legal_pack(row, session=session, access_config=legal_access)
    online_warnings = list(online_summary.get("warnings") or [])

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

    uploaded = [d for d in existing if (d.get("metadata") or {}).get("origin") == "user-upload"]
    prior_online = [d for d in existing if (d.get("metadata") or {}).get("origin") != "user-upload"]

    # Fresh online evidence replaces prior automatic evidence. If no fresh automatic
    # evidence is available, keep only the now-revalidated prior evidence so access
    # routes are not lost but stale trust cannot survive.
    if online_docs:
        combined = uploaded + online_docs
    else:
        combined = uploaded + prior_online

    # Always rebuild the entire legal summary from the combined *current-policy*
    # evidence set. This deliberately discards all derived fields/contacts/risks from
    # the old summary and is what purges stale passing rent/company/contact evidence.
    summary = analyse_legal_documents(combined, str(row.get("detail_text") or ""))
    summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + online_warnings))
    if prior_online and not online_docs:
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "Previously discovered legal links were retained only after revalidation because the current automatic acquisition attempt did not return a replacement pack."
        ]))
    if uploaded:
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "User-uploaded documents are included in this analysis alongside any permitted auctioneer documents."
        ]))
    for note in revalidation.get("notes") or []:
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [note]))
    summary["revalidation_report"] = revalidation
    summary["stored_upload_reprocess"] = stored_reparse
    if stored_reparse.get("reprocessed"):
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            f"Re-analysed {stored_reparse.get('reprocessed')} retained user-uploaded legal document(s) from the stored originals using the current parser."
        ]))
    for note in stored_reparse.get("notes") or []:
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [note]))

    # Compare against the revalidated prior snapshot, not the old trust labels. A
    # policy-driven downgrade is a purge event, not a provider pack-change alarm.
    change = compare_legal_documents(existing, combined)
    summary["pack_changed"] = bool(change.get("changed"))
    summary["pack_change"] = change
    if change.get("changed"):
        summary["warnings"] = list(dict.fromkeys((summary.get("warnings") or []) + [
            "Legal-pack evidence changed since the previous revalidated snapshot. Review added, removed or modified verified documents before bidding."
        ]))

    db.save_legal_bundle(row["id"], summary, combined)

    # Purge stale corporate enrichment whenever the refreshed legal evidence no
    # longer establishes a verified company identity. If the verified company changes,
    # also clear the old official bundle so it cannot appear against the new seller.
    extracted = summary.get("extracted_fields") or {}
    verified_company = bool(extracted.get("company_identity_verified")) and str(summary.get("status") or "").lower() == "verified"
    current_company_no = str(extracted.get("company_number") or "").strip()
    if hasattr(db, "company_intelligence_for") and hasattr(db, "clear_company_intelligence"):
        prior_company = db.company_intelligence_for(row["id"])
        prior_company_no = str(prior_company.get("company_number") or "").strip()
        if (not verified_company) or (prior_company_no and current_company_no and prior_company_no != current_company_no):
            db.clear_company_intelligence(row["id"])

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
    """Refresh Companies House intelligence only from a verified legal seller identity."""
    legal = db.legal_summary_for(row["id"])
    extracted = legal.get("extracted_fields") or {}
    field_sources = extracted.get("field_sources") or {}
    identity_verified = bool(extracted.get("company_identity_verified")) and str(legal.get("status") or "").lower() == "verified"
    if not identity_verified:
        summary = {
            "provider": "Companies House Public Data API",
            "status": "unresolved",
            "company_number": None,
            "company_name": None,
            "resolution": {},
            "error": "No verified corporate seller identity is available from lot-bound legal evidence. Companies House lookup was not run.",
        }
        db.save_company_intelligence(row["id"], summary)
        return summary
    company_number = str(extracted.get("company_number") or "").strip() if field_sources.get("company_number") == "verified legal document" else ""
    seller_name = str(extracted.get("seller_name") or extracted.get("proprietor_name") or "").strip()
    seller_source = field_sources.get("seller_name") or field_sources.get("proprietor_name")
    if seller_source != "verified legal document":
        seller_name = ""
    registered_office = str(extracted.get("registered_office") or "").strip() if field_sources.get("registered_office") == "verified legal document" else ""
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
        field_sources = extracted.get("field_sources") or {}
        if str(legal.get("status") or "").lower() != "verified" or not extracted.get("company_identity_verified"):
            continue
        seller_name = str(extracted.get("seller_name") or extracted.get("proprietor_name") or "")
        company_number = str(extracted.get("company_number") or "")
        companyish = (
            bool(company_number and field_sources.get("company_number") == "verified legal document")
            or bool(seller_name and (field_sources.get("seller_name") == "verified legal document" or field_sources.get("proprietor_name") == "verified legal document")
                    and re.search(r"\b(?:LTD|LIMITED|PLC|LLP)\b", seller_name, re.I))
        )
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
