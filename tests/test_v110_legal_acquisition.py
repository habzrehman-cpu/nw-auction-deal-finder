from tracker.legal_access import (
    LegalAccessConfig, ProviderAccess, config_from_mapping, provider_access_status, login_from_page,
)
from tracker import legal
from tracker.legal import analyse_legal_documents, fetch_legal_documents
from tracker.intelligence import build_vendor_story


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
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.headers = {}
        self.calls = []
        self.posts = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = self.routes[url]
        if isinstance(response, list):
            return response.pop(0)
        return response

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, data or {}))
        response = self.routes[url]
        if isinstance(response, list):
            return response.pop(0)
        return response


def test_access_config_and_provider_permission_gate():
    cfg = config_from_mapping({
        "legal_sources": {
            "auto_enabled": True,
            "auction_house": {"permission_confirmed": False, "email": "a@example.com", "password": "secret"},
            "savills": {"email": "s@example.com", "password": "secret"},
        }
    })
    ah = provider_access_status(cfg, "auction_house")
    assert ah["allowed"] is False
    assert "permission" in ah["status"]
    sav = provider_access_status(cfg, "savills")
    assert sav["allowed"] is True
    assert "authenticated" in sav["status"]


def test_permission_gate_prevents_auction_house_request():
    cfg = LegalAccessConfig(providers={"auction_house": ProviderAccess(permission_confirmed=False)})
    session = FakeSession()
    docs, warnings = fetch_legal_documents(
        {"source": "Auction House NW", "url": "https://www.auctionhouse.co.uk/northwest/auction/lot/1"},
        session=session,
        access_config=cfg,
    )
    assert docs == []
    assert session.calls == []
    assert any("permission" in w.lower() for w in warnings)


def test_public_legal_pdf_requires_property_identity_before_auto_acquisition(monkeypatch):
    lot_url = "https://www.eddisons.com/property-search/example"
    pdf_url = "https://www.eddisons.com/files/legal-pack.pdf"
    lot_html = '<html><a href="/files/legal-pack.pdf">Legal pack</a></html>'
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        pdf_url: FakeResponse(pdf_url, data=b"%PDF-fake", ctype="application/pdf"),
    })
    monkeypatch.setattr(legal, "extract_pdf_text", lambda data, max_chars=90000: "--- PAGE 1 ---\nTitle number: MAN123456")
    docs, warnings = fetch_legal_documents(
        {"source": "BTG Eddisons", "url": lot_url}, session=session, access_config=LegalAccessConfig()
    )
    parsed = [d for d in docs if d.get("text_content")]
    assert parsed == []
    assert docs and (docs[0].get("metadata") or {}).get("verified_for_lot") is False


def test_conventional_login_form_preserves_hidden_fields():
    login_url = "https://auctions.example/login"
    success_url = login_url
    login_html = '''
    <html><form method="post" action="/login">
      <input type="hidden" name="csrf" value="token123">
      <input type="email" name="email">
      <input type="password" name="password">
      <input type="submit" name="submit" value="Login">
    </form></html>
    '''
    session = FakeSession({
        login_url: [FakeResponse(login_url, login_html), FakeResponse(success_url, "<html>My account</html>")],
    })
    ok, message = login_from_page(session, login_url, "buyer@example.com", "pw123")
    assert ok is True
    assert session.posts
    _, payload = session.posts[0]
    assert payload["csrf"] == "token123"
    assert payload["email"] == "buyer@example.com"
    assert payload["password"] == "pw123"


def test_login_stops_on_captcha():
    login_url = "https://auctions.example/login"
    session = FakeSession({login_url: FakeResponse(login_url, '<div class="g-recaptcha"></div>')})
    ok, message = login_from_page(session, login_url, "buyer@example.com", "pw123")
    assert ok is False
    assert "captcha" in message.lower()
    assert not session.posts


def test_250_year_lease_cannot_keep_short_lease_risk():
    detail = (
        "Lease issue term 70 years. Length of Lease/Term: 250 years from 13 November 2003. "
        "Service charge GBP 4,195.33."
    )
    summary = analyse_legal_documents([], detail)
    assert summary["extracted_fields"]["lease_years_remaining"] > 80
    labels = {f["label"] for f in summary["risk_flags"]}
    assert "Possible sub-80-year lease" not in labels
    assert "Short lease" not in labels
    assert "Lease appears to have fewer than 80 years remaining" not in labels


def test_auctioneer_business_email_not_mislabelled_as_solicitor():
    docs = [{
        "name": "legal.pdf", "doc_type": "Legal pack", "url": "",
        "text_content": "--- PAGE 1 ---\nSolicitors Solaris Law. Auction House North West northwest@auctionhouse.co.uk 01772 772450",
        "sha256": "abc",
    }]
    summary = analyse_legal_documents(docs)
    assert summary["contacts"]
    assert summary["contacts"][0]["role"] == "Auctioneer"


def test_listing_probate_is_labelled_signal_not_confirmed():
    summary = analyse_legal_documents([], "Probate sale. Title number MAN115545")
    extracted = summary["extracted_fields"]
    assert extracted["seller_type"] == "Probate / estate"
    assert "signal" in extracted["seller_type_evidence"].lower()
    story = build_vendor_story(
        {"status": "Available post-auction", "detail_text": "Probate sale"},
        history=[], deal_analysis={"failure_count": 1, "price_reduction_pct": 10}, legal_summary=summary,
    )
    assert any("legal confirmation" in fact.lower() for fact in story["confirmed_facts"])


def test_sold_timeline_is_explicitly_auction_result_not_completion():
    story = build_vendor_story(
        {"status": "Live"},
        history=[{"status": "Sold Prior", "auction_date": "01/09/2026", "guide_price": 100000}],
        deal_analysis={}, legal_summary={}, planning_items=[]
    )
    assert story["timeline"][0]["label"].startswith("Auction result:")
    assert "not proof" in story["timeline"][0]["detail"].lower()


def test_savills_authenticated_legal_pack_can_be_retrieved(monkeypatch):
    lot_url = "https://auctions.savills.co.uk/auctions/lot-1"
    legal_url = "https://auctions.savills.co.uk/legal/lot-1"
    login_url = "https://auctions.savills.co.uk/login"
    pdf_url = "https://auctions.savills.co.uk/downloads/title.pdf"
    lot_html = '<a href="/legal/lot-1">Legal documents</a>'
    login_html = '''<form method="post" action="/login">
      <input type="hidden" name="csrf" value="abc">
      <input type="email" name="email"><input type="password" name="password">
      <input type="submit" name="submit" value="Login"></form>'''
    pack_html = '<html><h1>Legal documents for Lot 1, SW1A 1AA</h1><a href="/downloads/title.pdf">Title register</a></html>'
    session = FakeSession({
        lot_url: FakeResponse(lot_url, lot_html),
        legal_url: [FakeResponse(legal_url, login_html), FakeResponse(legal_url, login_html), FakeResponse(legal_url, pack_html)],
        login_url: FakeResponse(login_url, "<html>Account home</html>"),
        pdf_url: FakeResponse(pdf_url, data=b"%PDF-auth", ctype="application/pdf"),
    })
    monkeypatch.setattr(legal, "extract_pdf_text", lambda data, max_chars=90000: "--- PAGE 1 ---\nProperty: 1 Example Street, London SW1A 1AA\nTitle number: NGL123456")
    cfg = LegalAccessConfig(providers={"savills": ProviderAccess(email="buyer@example.com", password="pw")})
    docs, warnings = fetch_legal_documents({"source": "Savills", "url": lot_url, "postcode": "SW1A 1AA", "lot_number": "1", "address": "1 Example Street, London, SW1A 1AA"}, session=session, access_config=cfg)
    parsed = [d for d in docs if d.get("text_content") and d.get("url") == pdf_url]
    assert parsed
    assert parsed[0]["metadata"]["origin"] == "auto-download-authenticated"
    assert session.posts and session.posts[0][0] == login_url


def test_auto_downloaded_original_is_retained_in_private_cloud(monkeypatch):
    from tracker import diligence

    class FakeDB:
        def __init__(self):
            self.saved = None
        def legal_documents_for(self, property_id):
            return []
        def save_legal_bundle(self, property_id, summary, documents):
            self.saved = (property_id, summary, documents)

    class FakeCloud:
        def __init__(self):
            self.uploads = []
        def upload_legal_document(self, property_id, filename, data, sha256):
            self.uploads.append((property_id, filename, data, sha256))
            return f"legal-packs/{property_id}/{filename}"

    summary = analyse_legal_documents([], "")
    doc = {
        "name": "title.pdf", "url": "https://example/title.pdf", "doc_type": "Title register",
        "access_status": "public PDF parsed", "text_content": "--- PAGE 1 ---\nTitle number MAN123456",
        "sha256": "abcdef", "metadata": {"origin": "auto-download-public"}, "_raw_bytes": b"%PDF-bytes",
    }
    monkeypatch.setattr(diligence, "analyse_online_legal_pack", lambda row, session=None, access_config=None: (summary, [doc.copy()]))
    db = FakeDB(); cloud = FakeCloud()
    diligence.refresh_property_legal(db, {"id": 7, "detail_text": ""}, cloud_store=cloud)
    assert cloud.uploads
    saved_doc = db.saved[2][0]
    assert saved_doc["metadata"]["cloud_storage_path"].startswith("legal-packs/7/")
    assert "_raw_bytes" not in saved_doc
