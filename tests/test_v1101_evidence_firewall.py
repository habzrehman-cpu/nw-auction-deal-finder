from tracker import legal
from tracker.legal import (
    analyse_legal_documents, compare_legal_documents, discover_legal_links,
    fetch_legal_documents, uploaded_document,
)
from tracker.legal_access import LegalAccessConfig
from tracker.legal_firewall import (
    EVIDENCE_POLICY_VERSION, TIER_CANDIDATE, TIER_VERIFIED_LEGAL,
)
from tracker.diligence import refresh_property_company


class FakeResponse:
    def __init__(self, url, text="", data=None, ctype="text/html", status=200):
        self.url = url
        self.text = text
        self._data = data if data is not None else text.encode("utf-8")
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(self._data))}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield self._data


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = self.routes[url]
        if isinstance(response, list):
            return response.pop(0)
        return response


def test_first_hop_rejects_generic_lease_advisory_navigation():
    html = '''
    <a href="/legal/lot-11">Legal pack</a>
    <a href="/services/lease-advisory">Lease advisory</a>
    <a href="/property-search">Property search</a>
    '''
    links = discover_legal_links(html, "https://www.eddisons.com/property-search/lot-11", pack_context=False)
    urls = [x["url"] for x in links]
    assert "https://www.eddisons.com/legal/lot-11" in urls
    assert not any("lease-advisory" in x for x in urls)
    assert not any(x.endswith("/property-search") for x in urls)


def test_generic_advisory_page_cannot_become_legal_evidence_or_be_crawled():
    lot_url = "https://www.eddisons.com/property-search/lot-11"
    advisory_url = "https://www.eddisons.com/services/lease-advisory"
    lot_html = '<a href="/services/lease-advisory">Legal documents</a>'
    advisory_html = '''<html><h1>Lease advisory</h1>
      Company number 05120043. Passing rent GBP 750000.
      <a href="/services/random.pdf">Document</a>
    </html>'''
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        advisory_url: FakeResponse(advisory_url, advisory_html),
    })
    docs, _ = fetch_legal_documents(
        {"source": "BTG Eddisons", "url": lot_url, "postcode": "PE19 5EE", "lot_number": "11"},
        session=session, access_config=LegalAccessConfig(),
    )
    assert docs == []
    assert advisory_url not in session.calls
    assert not any("random.pdf" in call for call in session.calls)
    summary = analyse_legal_documents(docs, "")
    assert summary["status"] == "not-found"
    assert summary["extracted_fields"].get("company_number") is None
    assert summary["risk_flags"] == []


def test_verified_pack_index_allows_child_pdf_without_requiring_address_in_every_pdf(monkeypatch):
    lot_url = "https://www.eddisons.com/property-search/lot-11"
    pack_url = "https://www.eddisons.com/legal/lot-11"
    pdf_url = "https://www.eddisons.com/downloads/title-11.pdf"
    lot_html = '<a href="/legal/lot-11">Legal pack</a>'
    pack_html = '<h1>Legal pack for PE19 5EE Lot 11</h1><a href="/downloads/title-11.pdf">Title register</a>'
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        pack_url: FakeResponse(pack_url, pack_html),
        pdf_url: FakeResponse(pdf_url, data=b"%PDF-title", ctype="application/pdf"),
    })
    monkeypatch.setattr(legal, "extract_pdf_text", lambda data, max_chars=90000: "--- PAGE 1 ---\nTitle Number: CB123456")
    docs, _ = fetch_legal_documents(
        {"source": "BTG Eddisons", "url": lot_url, "postcode": "PE19 5EE", "lot_number": "11"},
        session=session, access_config=LegalAccessConfig(),
    )
    verified = [d for d in docs if (d.get("metadata") or {}).get("evidence_tier") == TIER_VERIFIED_LEGAL]
    assert len(verified) == 1
    assert verified[0]["url"] == pdf_url
    summary = analyse_legal_documents(docs)
    assert summary["status"] == "verified"
    assert summary["verified_document_count"] == 1
    assert summary["extracted_fields"]["title_number"] == "CB123456"


def test_candidate_provider_company_number_cannot_feed_seller_identity_or_contacts():
    docs = [{
        "name": "Lease advisory", "doc_type": "Legal document", "url": "https://www.eddisons.com/services/lease-advisory",
        "text_content": "Company number 05120043. Solicitor 0333 200 2039. Overage clawback.",
        "sha256": "abc", "metadata": {"evidence_tier": TIER_CANDIDATE, "verified_for_lot": False},
    }]
    summary = analyse_legal_documents(docs)
    assert summary["status"] == "candidates-only"
    assert summary["extracted_fields"].get("company_number") is None
    assert summary["contacts"] == []
    assert summary["risk_flags"] == []
    assert summary["risk_score"] == 0


def test_persisted_legacy_document_is_quarantined_until_refreshed():
    docs = [{
        "name": "Legacy page", "doc_type": "Legal document", "url": "https://provider.test/page",
        "text_content": "PROPRIETOR: WRONG COMPANY PLC Company number 01234567", "sha256": "abc", "metadata": {},
    }]
    summary = analyse_legal_documents(docs)
    assert summary["status"] == "candidates-only"
    assert summary["verified_document_count"] == 0
    assert summary["evidence_policy_version"] == EVIDENCE_POLICY_VERSION
    assert summary["extracted_fields"].get("company_number") is None


def test_user_uploaded_document_is_verified_legal_evidence():
    doc = uploaded_document(
        "Official Copy Register.txt",
        b"Title Number: GM123456\nPROPRIETOR: REAL OWNER LIMITED\nCompany number: 01234567",
    )
    summary = analyse_legal_documents([doc])
    assert summary["status"] == "verified"
    assert summary["verified_document_count"] == 1
    assert summary["extracted_fields"]["company_number"] == "01234567"
    assert summary["extracted_fields"]["company_identity_verified"] is True


def test_companies_house_lookup_is_blocked_without_verified_legal_identity():
    class FakeDB:
        def __init__(self):
            self.saved = None
        def legal_summary_for(self, property_id):
            return {
                "status": "candidates-only",
                "extracted_fields": {"company_number": "05120043", "company_identity_verified": False},
            }
        def save_company_intelligence(self, property_id, summary):
            self.saved = summary

    db = FakeDB()
    result = refresh_property_company(db, {"id": 1}, "unused-key")
    assert result["status"] == "unresolved"
    assert result["company_number"] is None
    assert "not run" in result["error"].lower()
    assert db.saved == result


def test_pack_change_alarm_ignores_candidate_pages_but_tracks_verified_docs():
    candidate_old = [{
        "name": "advisory", "url": "https://x.test/advisory", "sha256": "aaa", "doc_type": "Legal document",
        "metadata": {"evidence_tier": TIER_CANDIDATE, "verified_for_lot": False},
    }]
    candidate_new = [{
        "name": "advisory", "url": "https://x.test/advisory", "sha256": "bbb", "doc_type": "Legal document",
        "metadata": {"evidence_tier": TIER_CANDIDATE, "verified_for_lot": False},
    }]
    assert compare_legal_documents(candidate_old, candidate_new)["changed"] is False

    verified_old = [{
        "name": "Special Conditions.pdf", "url": "https://x.test/special.pdf", "sha256": "aaa", "doc_type": "Special conditions",
        "metadata": {"evidence_tier": TIER_VERIFIED_LEGAL, "verified_for_lot": True},
    }]
    verified_new = [{
        "name": "Special Conditions.pdf", "url": "https://x.test/special.pdf", "sha256": "bbb", "doc_type": "Special conditions",
        "metadata": {"evidence_tier": TIER_VERIFIED_LEGAL, "verified_for_lot": True},
    }]
    change = compare_legal_documents(verified_old, verified_new)
    assert change["changed"] is True
    assert change["modified"] == ["Special Conditions.pdf"]


def test_listing_text_can_create_labelled_signal_but_not_legal_risk_or_company_identity():
    summary = analyse_legal_documents([], "Probate sale. Company number 05120043. Overage applies. Lease remaining 70 years.")
    assert summary["status"] == "not-found"
    assert summary["extracted_fields"]["seller_type"] == "Probate / estate"
    assert "auctioneer" in summary["extracted_fields"]["seller_type_evidence"].lower()
    assert summary["extracted_fields"].get("company_number") is None
    assert summary["risk_flags"] == []
    assert summary["risk_score"] == 0

def test_html_legal_pack_label_alone_does_not_verify_unidentified_destination():
    lot_url = "https://www.eddisons.com/property-search/lot-11"
    landing_url = "https://www.eddisons.com/legal-documents"
    lot_html = '<a href="/legal-documents">Legal pack</a>'
    landing_html = '<h1>Legal documents</h1><a href="/downloads/lease.pdf">Lease</a>'
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        landing_url: FakeResponse(landing_url, landing_html),
    })
    docs, _ = fetch_legal_documents(
        {"source": "BTG Eddisons", "url": lot_url, "postcode": "PE19 5EE", "lot_number": "11"},
        session=session, access_config=LegalAccessConfig(),
    )
    assert len(docs) == 1
    assert (docs[0].get("metadata") or {}).get("evidence_tier") == TIER_CANDIDATE
    assert not any("lease.pdf" in call for call in session.calls)


def test_verified_pack_index_does_not_trust_unrelated_binary_navigation(monkeypatch):
    lot_url = "https://www.eddisons.com/property-search/lot-11"
    pack_url = "https://www.eddisons.com/legal/lot-11"
    brochure_url = "https://www.eddisons.com/downloads/corporate-report.pdf"
    lot_html = '<a href="/legal/lot-11">Legal pack</a>'
    pack_html = '<h1>Legal pack PE19 5EE Lot 11</h1><a href="/downloads/corporate-report.pdf">Download</a>'
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        pack_url: FakeResponse(pack_url, pack_html),
        brochure_url: FakeResponse(brochure_url, data=b"%PDF-corp", ctype="application/pdf"),
    })
    monkeypatch.setattr(legal, "extract_pdf_text", lambda data, max_chars=90000: "--- PAGE 1 ---\nBTG corporate report company number 05120043")
    docs, _ = fetch_legal_documents(
        {"source": "BTG Eddisons", "url": lot_url, "postcode": "PE19 5EE", "lot_number": "11"},
        session=session, access_config=LegalAccessConfig(),
    )
    target = next(d for d in docs if d.get("url") == brochure_url)
    assert (target.get("metadata") or {}).get("evidence_tier") == TIER_CANDIDATE
    summary = analyse_legal_documents(docs)
    assert summary["extracted_fields"].get("company_number") is None
    assert summary["verified_document_count"] == 0

def test_stored_company_intelligence_cannot_reenter_story_without_verified_legal_identity():
    from tracker.intelligence import build_vendor_story
    lot = {"status": "Live", "title": "Subject lot", "raw_text": "", "detail_text": ""}
    legal_summary = {
        "status": "candidates-only",
        "extracted_fields": {"company_number": "05120043", "company_identity_verified": False, "field_sources": {}},
    }
    stale_company = {
        "status": "ok", "company_name": "BTG CONSULTING PLC", "company_number": "05120043",
        "company_status": "active", "corporate_pressure_score": 8.0,
        "insolvency_case_count": 1, "company_url": "https://find-and-update.company-information.service.gov.uk/company/05120043",
    }
    story = build_vendor_story(lot, [], {}, legal_summary, [], stale_company)
    assert story["seller_profile"].get("company_number") is None
    assert story["seller_profile"].get("company_name_verified") is None
    assert not any("Companies House" in fact for fact in story["confirmed_facts"])
    assert not any("corporate" in reason.lower() for reason in story.get("leverage_reasons", []))
    assert not any("corporate" in inference.lower() for inference in story.get("inferences", []))


def test_candidate_metric_counts_only_unverified_items():
    verified = uploaded_document("Title register.txt", b"Title Number: GM123456")
    candidate = {
        "name": "Provider page", "doc_type": "Legal document", "url": "https://example.test/services",
        "text_content": "", "sha256": "", "metadata": {"evidence_tier": TIER_CANDIDATE, "verified_for_lot": False},
    }
    summary = analyse_legal_documents([verified, candidate])
    assert summary["document_count"] == 2
    assert summary["verified_document_count"] == 1
    assert summary["candidate_document_count"] == 1
