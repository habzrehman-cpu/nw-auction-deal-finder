from pathlib import Path

from tracker.db import Database
from tracker.legal import analyse_legal_documents, revalidate_saved_legal_documents, uploaded_document
from tracker.legal_firewall import (
    EVIDENCE_POLICY_VERSION, TIER_REJECTED, TIER_VERIFIED_LEGAL,
)
from tracker import diligence


def subject_lot():
    return {
        "id": 1,
        "source": "BTG Eddisons",
        "url": "https://www.eddisons.com/property-search/lot-13",
        "postcode": "PE19 5EE",
        "lot_number": "13",
        "address": "The Old Exchange, Park Lane, Stoneley, Kimbolton, PE19 5EE",
        "detail_text": "",
    }


def stale_cross_property_doc():
    return {
        "name": "Legal document",
        "doc_type": "Lease",
        "url": "https://www.eddisons.com/downloads/great-chesterford.pdf",
        "access_status": "verified public legal PDF parsed",
        "text_content": (
            "--- PAGE 1 ---\nProperty: Great Chesterford Court, Great Chesterford, Saffron Walden CB10 1PF\n"
            "Passing rent GBP 18,000\nCompany number 05120043\nSolicitor 0333 200 2039"
        ),
        "sha256": "old-cross-property",
        "metadata": {
            "origin": "auto-download-public",
            "evidence_tier": TIER_VERIFIED_LEGAL,
            "verified_for_lot": True,
            "identity_status": "verified",
            "identity_score": 80,
            "evidence_policy_version": "1.10.2-identity-lock",
            "source_property_url": "https://www.eddisons.com/property-search/lot-13",
        },
    }


def test_saved_cross_property_verified_doc_is_rejected_and_derived_evidence_disappears():
    lot = subject_lot()
    docs, report = revalidate_saved_legal_documents(lot, [stale_cross_property_doc()])
    assert len(docs) == 1
    assert (docs[0].get("metadata") or {}).get("evidence_tier") == TIER_REJECTED
    assert report["downgraded"] == 1
    assert report["rejected"] == 1
    assert report["purged_findings"] == 1

    summary = analyse_legal_documents(docs)
    assert summary["verified_document_count"] == 0
    assert summary["risk_score"] == 0
    assert summary["contacts"] == []
    assert summary["evidence"] == []
    assert summary["extracted_fields"].get("tenancy_rent_amount") is None
    assert summary["extracted_fields"].get("company_number") is None


def test_user_upload_survives_revalidation_and_gets_current_policy_stamp():
    lot = subject_lot()
    doc = uploaded_document(
        "Official Copy Register.txt",
        b"Property: The Old Exchange Park Lane PE19 5EE\nTitle Number: CB123456",
    )
    docs, report = revalidate_saved_legal_documents(lot, [doc])
    assert report["user_uploads"] == 1
    assert report["retained_verified"] == 1
    meta = docs[0]["metadata"]
    assert meta["evidence_tier"] == TIER_VERIFIED_LEGAL
    assert meta["evidence_policy_version"] == EVIDENCE_POLICY_VERSION
    assert meta["revalidation_outcome"] == "retained-user-upload"


def _insert_subject(db):
    db.upsert({
        "source": "BTG Eddisons", "source_key": "ed-13",
        "url": "https://www.eddisons.com/property-search/lot-13",
        "title": "The Old Exchange, Park Lane, Stoneley, Kimbolton PE19 5EE",
        "address": "The Old Exchange, Park Lane, Stoneley, Kimbolton, PE19 5EE",
        "postcode": "PE19 5EE", "area": "Cambridgeshire", "property_type": "Commercial",
        "lot_number": "13", "guide_text": "GBP 185,000", "guide_price": 185000,
        "result_text": "", "result_price": None, "status": "Live", "auction_date": "",
        "raw_text": "commercial auction property",
    })
    return db.property_for_key("ed-13")


def test_refresh_purges_old_summary_and_stale_company_intelligence_when_provider_returns_nothing(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "tracker.db")
    row = _insert_subject(db)
    stale = stale_cross_property_doc()
    stale_summary = analyse_legal_documents([stale])
    # Simulate an old build having trusted the cross-property file.
    stale_summary.update({
        "status": "verified",
        "verified_document_count": 1,
        "parsed_document_count": 1,
        "risk_score": 3.0,
        "evidence_policy_version": "1.10.2-identity-lock",
        "extracted_fields": {
            "company_number": "05120043", "company_identity_verified": True,
            "tenancy_rent_amount": 18000,
            "field_sources": {"company_number": "verified legal document", "tenancy_rent_amount": "verified legal document"},
        },
        "contacts": [{"role": "Solicitor", "phone": "0333 200 2039"}],
        "evidence": [{"finding": "Passing rent", "value": 18000, "document": "Legal document"}],
    })
    db.save_legal_bundle(row["id"], stale_summary, [stale])
    db.save_company_intelligence(row["id"], {
        "provider": "Companies House Public Data API", "status": "ok",
        "company_number": "05120043", "company_name": "BTG CONSULTING PLC",
        "company_status": "active", "registered_office": "340 Deansgate, Manchester",
        "corporate_pressure_score": 0,
    })

    monkeypatch.setattr(
        diligence,
        "analyse_online_legal_pack",
        lambda *args, **kwargs: ({"warnings": ["provider returned no replacement pack"]}, []),
    )

    summary = diligence.refresh_property_legal(db, row)
    saved = db.legal_summary_for(row["id"])
    docs = db.legal_documents_for(row["id"])

    assert saved["evidence_policy_version"] == EVIDENCE_POLICY_VERSION
    assert saved["verified_document_count"] == 0
    assert saved["risk_score"] == 0
    assert saved["contacts"] == []
    assert saved["evidence"] == []
    assert saved["extracted_fields"].get("tenancy_rent_amount") is None
    assert saved["extracted_fields"].get("company_number") is None
    assert saved["revalidation_report"]["purged_findings"] == 1
    assert (docs[0].get("metadata") or {}).get("evidence_tier") == TIER_REJECTED
    assert db.company_intelligence_for(row["id"]) == {}
    assert summary["status"] in {"candidates-only", "not-found"}
