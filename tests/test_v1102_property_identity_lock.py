from tracker import legal
from tracker.legal import analyse_legal_documents, fetch_legal_documents
from tracker.legal_access import LegalAccessConfig
from tracker.legal_firewall import (
    TIER_REJECTED, TIER_VERIFIED_LEGAL, document_identity_assessment,
    document_type_classification,
)


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

    def get(self, url, **kwargs):
        value = self.routes[url]
        if isinstance(value, list):
            return value.pop(0)
        return value


def subject_lot():
    return {
        "source": "BTG Eddisons",
        "url": "https://www.eddisons.com/property-search/lot-13",
        "postcode": "PE19 5EE",
        "lot_number": "13",
        "address": "The Old Exchange, Park Lane, Stoneley, Kimbolton, PE19 5EE",
    }


def test_exact_subject_postcode_and_legal_class_pass_identity_lock():
    lot = subject_lot()
    text = "Property: The Old Exchange, Park Lane, Stoneley, Kimbolton PE19 5EE. Title Number CB123456"
    assessment = document_identity_assessment(lot, text=text, url="https://www.eddisons.com/legal/title.pdf", label="Title register")
    doc_class = document_type_classification("Title register", "https://www.eddisons.com/legal/title.pdf", text)
    assert assessment["score"] >= 60
    assert assessment["status"] == "verified"
    assert doc_class["allowed"] is True
    assert doc_class["doc_type"] == "Title register"


def test_explicit_different_property_postcode_is_hard_rejected():
    lot = subject_lot()
    text = "Property: Great Chesterford Court, Great Chesterford, Saffron Walden CB10 1PF. Passing rent GBP 18,000."
    assessment = document_identity_assessment(lot, text=text, url="https://www.eddisons.com/files/lease.pdf", label="Lease")
    assert assessment["hard_reject"] is True
    assert assessment["status"] == "rejected"
    assert any("different property postcode" in x for x in assessment["conflicts"])


def test_cross_property_pdf_is_retained_for_audit_but_excluded_from_legal_analysis(monkeypatch):
    lot = subject_lot()
    pack_url = "https://www.eddisons.com/legal/lot-13"
    wrong_pdf = "https://www.eddisons.com/legal/great-chesterford-lease.pdf"
    lot_html = '<a href="/legal/lot-13">Legal pack</a>'
    pack_html = '<h1>Legal pack PE19 5EE Lot 13</h1><a href="/legal/great-chesterford-lease.pdf">Lease</a>'
    session = FakeSession({
        lot["url"]: FakeResponse(lot["url"], lot_html),
        pack_url: FakeResponse(pack_url, pack_html),
        wrong_pdf: FakeResponse(wrong_pdf, data=b"%PDF-wrong", ctype="application/pdf"),
    })
    monkeypatch.setattr(
        legal, "extract_pdf_text",
        lambda data, max_chars=90000: "--- PAGE 1 ---\nProperty: Great Chesterford Court, Great Chesterford CB10 1PF\nPassing rent GBP 18,000",
    )
    docs, _ = fetch_legal_documents(lot, session=session, access_config=LegalAccessConfig())
    wrong = next(d for d in docs if d.get("url") == wrong_pdf)
    assert (wrong.get("metadata") or {}).get("evidence_tier") == TIER_REJECTED
    assert wrong.get("text_content") == ""
    summary = analyse_legal_documents(docs)
    assert summary["verified_document_count"] == 0
    assert summary["rejected_document_count"] >= 1
    assert summary["extracted_fields"].get("tenancy_rent_amount") is None


def test_matching_title_register_is_verified_and_can_supply_evidence(monkeypatch):
    lot = subject_lot()
    pack_url = "https://www.eddisons.com/legal/lot-13"
    title_pdf = "https://www.eddisons.com/legal/title-register.pdf"
    lot_html = '<a href="/legal/lot-13">Legal pack</a>'
    pack_html = '<h1>Legal pack PE19 5EE Lot 13</h1><a href="/legal/title-register.pdf">Title register</a>'
    session = FakeSession({
        lot["url"]: FakeResponse(lot["url"], lot_html),
        pack_url: FakeResponse(pack_url, pack_html),
        title_pdf: FakeResponse(title_pdf, data=b"%PDF-right", ctype="application/pdf"),
    })
    monkeypatch.setattr(
        legal, "extract_pdf_text",
        lambda data, max_chars=90000: "--- PAGE 1 ---\nProperty: The Old Exchange, Park Lane, Stoneley, Kimbolton PE19 5EE\nTitle Number: CB123456",
    )
    docs, _ = fetch_legal_documents(lot, session=session, access_config=LegalAccessConfig())
    target = next(d for d in docs if d.get("url") == title_pdf)
    assert (target.get("metadata") or {}).get("evidence_tier") == TIER_VERIFIED_LEGAL
    assert (target.get("metadata") or {}).get("identity_score") >= 60
    summary = analyse_legal_documents(docs)
    assert summary["verified_document_count"] == 1
    assert summary["extracted_fields"].get("title_number") == "CB123456"


def test_marketing_brochure_is_not_legal_even_when_subject_postcode_matches(monkeypatch):
    lot = subject_lot()
    pdf_url = "https://www.eddisons.com/files/marketing-brochure.pdf"
    lot_html = '<a href="/files/marketing-brochure.pdf">Legal documents</a>'
    session = FakeSession({
        lot["url"]: FakeResponse(lot["url"], lot_html),
        pdf_url: FakeResponse(pdf_url, data=b"%PDF-brochure", ctype="application/pdf"),
    })
    monkeypatch.setattr(
        legal, "extract_pdf_text",
        lambda data, max_chars=90000: "--- PAGE 1 ---\nMarketing brochure for The Old Exchange, Park Lane, PE19 5EE",
    )
    docs, _ = fetch_legal_documents(lot, session=session, access_config=LegalAccessConfig())
    target = next(d for d in docs if d.get("url") == pdf_url)
    assert (target.get("metadata") or {}).get("evidence_tier") != TIER_VERIFIED_LEGAL
    assert analyse_legal_documents(docs)["verified_document_count"] == 0
