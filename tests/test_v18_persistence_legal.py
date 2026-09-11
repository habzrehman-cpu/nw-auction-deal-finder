from io import BytesIO
from pathlib import Path
import zipfile

from tracker.cloud import CloudConfig, SupabaseStorage, config_from_mapping
from tracker.db import Database
from tracker.legal import analyse_legal_documents, uploaded_documents


class FakeResponse:
    def __init__(self, status=200, content=b"", json_data=None):
        self.status_code = status
        self.content = content
        self._json = json_data
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self._json


class FakeSession:
    def __init__(self, remote_db=b""):
        self.remote_db = remote_db
        self.calls = []
    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers, None))
        if "/storage/v1/bucket/" in url:
            return FakeResponse(200, b"{}")
        if "/object/authenticated/" in url:
            return FakeResponse(200 if self.remote_db else 404, self.remote_db)
        return FakeResponse(404)
    def post(self, url, headers=None, json=None, data=None, timeout=None):
        self.calls.append(("POST", url, headers, data if data is not None else json))
        return FakeResponse(200, b"{}")
    def put(self, url, headers=None, data=None, timeout=None):
        self.calls.append(("PUT", url, headers, data))
        return FakeResponse(200, b"{}")


def test_new_supabase_secret_key_uses_apikey_not_bearer():
    store = SupabaseStorage(CloudConfig(url="https://abc.supabase.co", secret_key="sb_secret_test"), session=FakeSession())
    headers = store._headers()
    assert headers["apikey"] == "sb_secret_test"
    assert "Authorization" not in headers


def test_legacy_service_role_can_use_bearer():
    store = SupabaseStorage(CloudConfig(url="https://abc.supabase.co", secret_key="eyJlegacy"), session=FakeSession())
    headers = store._headers()
    assert headers["Authorization"] == "Bearer eyJlegacy"


def test_cloud_restore_and_upload_database(tmp_path):
    remote = b"SQLite format 3\x00example"
    session = FakeSession(remote_db=remote)
    store = SupabaseStorage(CloudConfig(url="https://abc.supabase.co", secret_key="sb_secret_test"), session=session)
    local = tmp_path / "auction_tracker.db"
    restored = store.restore_database_if_missing(local)
    assert restored["restored"] is True
    assert local.read_bytes() == remote
    synced = store.upload_database(local)
    assert synced["synced"] is True
    assert any(call[0] == "POST" and call[3] == remote for call in session.calls)


def test_uploaded_zip_legal_pack_parses_supported_members():
    buff = BytesIO()
    with zipfile.ZipFile(buff, "w") as z:
        z.writestr("Official Copy Register.txt", "Title number: GM123456\nPROPRIETOR: EXAMPLE PROPERTY LTD\n")
        z.writestr("Special Conditions.txt", "Completion 20 working days\nDeposit 10%\n")
        z.writestr("ignore.jpg", b"not parsed")
    docs = uploaded_documents("legal-pack.zip", buff.getvalue())
    assert len(docs) == 2
    assert all(d.get("_raw_bytes") for d in docs)
    assert {d["doc_type"] for d in docs} >= {"Title register", "Special conditions"}


def test_legal_analysis_has_page_audit_trail_and_completeness():
    docs = [
        {
            "name": "Official Copy Register.pdf", "doc_type": "Title register", "url": "", "access_status": "uploaded and parsed",
            "text_content": "--- PAGE 1 ---\nTitle Number: GM123456\nPROPRIETOR: EXAMPLE PROPERTY LTD\n--- PAGE 2 ---\nREGISTERED CHARGE dated 2024.\n",
            "sha256": "a",
        },
        {
            "name": "Special Conditions.pdf", "doc_type": "Special conditions", "url": "", "access_status": "uploaded and parsed",
            "text_content": "--- PAGE 3 ---\nCompletion shall take place 20 working days after exchange. Deposit 10%.\nBuyer shall reimburse the Seller legal costs of GBP 2500.\n",
            "sha256": "b",
        },
        {"name": "Title Plan.pdf", "doc_type": "Title plan", "url": "", "access_status": "uploaded; no extractable text", "text_content": "", "sha256": "c"},
    ]
    summary = analyse_legal_documents(docs)
    assert summary["status"] == "verified"
    assert summary["pack_completeness_pct"] == 100
    assert summary["extracted_fields"]["title_number"] == "GM123456"
    title_ev = next(e for e in summary["evidence"] if e["finding"] == "Title number")
    assert title_ev["document"] == "Official Copy Register.pdf"
    assert title_ev["page"] == 1
    assert summary["completion_days"] == 20


def test_db_roundtrip_preserves_legal_evidence_and_cloud_path(tmp_path: Path):
    db = Database(tmp_path / "tracker.db")
    db.upsert({
        "source": "Test", "source_key": "p1", "title": "1 Test Street", "address": "1 Test Street", "postcode": "M1 1AA",
        "area": "Greater Manchester", "property_type": "Flat", "status": "Live", "guide_price": 100000,
        "guide_text": "GBP 100,000", "auction_date": "2026-10-01", "raw_text": "",
    })
    pid = db.property_for_key("p1")["id"]
    summary = analyse_legal_documents([{
        "name": "register.pdf", "doc_type": "Title register", "access_status": "uploaded and parsed",
        "text_content": "--- PAGE 1 ---\nTitle Number: GM123456\nPROPRIETOR: EXAMPLE LTD\n", "sha256": "abc",
        "metadata": {"origin": "user-upload", "cloud_storage_path": "legal-packs/1/abc-register.pdf"},
    }])
    docs = [{
        "name": "register.pdf", "doc_type": "Title register", "access_status": "uploaded, parsed and stored privately",
        "text_content": "--- PAGE 1 ---\nTitle Number: GM123456\nPROPRIETOR: EXAMPLE LTD\n", "sha256": "abc", "url": "",
        "metadata": {"origin": "user-upload", "cloud_storage_path": "legal-packs/1/abc-register.pdf"},
    }]
    db.save_legal_bundle(pid, summary, docs)
    saved = db.legal_summary_for(pid)
    assert saved["evidence"][0]["page"] == 1
    assert isinstance(saved["missing_components"], list)
    stored_doc = db.legal_documents_for(pid)[0]
    assert stored_doc["metadata"]["cloud_storage_path"].startswith("legal-packs/")

def test_legal_extracts_company_registered_office_and_title_price_paid():
    docs = [{
        "name": "Official Copy Register.pdf", "doc_type": "Title register", "access_status": "uploaded and parsed", "sha256": "x",
        "text_content": (
            "--- PAGE 1 ---\nTitle Number: GM999999\n"
            "PROPRIETOR: NORTH WEST ASSETS LTD whose registered office is 10 King Street, Manchester M1 1AA\n"
            "Company number: 12345678\n"
            "The price stated to have been paid on 25 November 2024 was GBP 172,500.\n"
        ),
    }]
    summary = analyse_legal_documents(docs)
    fields = summary["extracted_fields"]
    assert fields["company_number"] == "12345678"
    assert fields["registered_office"].startswith("10 King Street")
    assert fields["title_price_paid"] == 172500
    assert fields["title_price_paid_date"] == "2024-11-25"

class FakeS3Body:
    def __init__(self, data): self.data = data
    def read(self): return self.data

class FakeS3:
    def __init__(self, remote=b""):
        self.remote = remote
        self.puts = []
        self.created = []
    def head_bucket(self, Bucket): return {"ok": True}
    def create_bucket(self, Bucket): self.created.append(Bucket); return {"ok": True}
    def get_object(self, Bucket, Key): return {"Body": FakeS3Body(self.remote)}
    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append((Bucket, Key, Body, ContentType)); self.remote = Body; return {"ok": True}


def test_preferred_s3_persistence_mode(tmp_path):
    fake = FakeS3(remote=b"SQLite format 3\x00remote")
    cfg = CloudConfig(
        bucket="nw-auction-private", s3_endpoint="https://ref.storage.supabase.co/storage/v1/s3",
        s3_region="eu-west-2", s3_access_key_id="access", s3_secret_access_key="secret"
    )
    store = SupabaseStorage(cfg, s3_client=fake)
    assert store.mode == "s3"
    local = tmp_path / "db.sqlite"
    assert store.restore_database_if_missing(local)["restored"] is True
    assert local.read_bytes().startswith(b"SQLite format 3")
    local.write_bytes(b"changed")
    assert store.upload_database(local)["synced"] is True
    assert fake.puts[-1][2] == b"changed"


class FakeS3HeadFailsButPutWorks(FakeS3):
    def head_bucket(self, Bucket):
        raise RuntimeError("HEAD not available")
    def create_bucket(self, Bucket):
        raise AssertionError("existing Supabase bucket must not be auto-created")


def test_s3_sync_does_not_mask_head_failure_with_create_bucket(tmp_path):
    fake = FakeS3HeadFailsButPutWorks()
    cfg = CloudConfig(
        bucket="nw-auction-private", s3_endpoint="https://ref.storage.supabase.co/storage/v1/s3",
        s3_region="eu-west-2", s3_access_key_id="access", s3_secret_access_key="secret"
    )
    store = SupabaseStorage(cfg, s3_client=fake)
    local = tmp_path / "db.sqlite"
    local.write_bytes(b"SQLite format 3\x00local")
    result = store.upload_database(local)
    assert result["synced"] is True
    assert fake.puts[-1][0] == "nw-auction-private"
    assert fake.created == []


def test_s3_client_uses_supabase_compatible_botocore_config():
    cfg = CloudConfig(
        bucket="nw-auction-private",
        s3_endpoint="https://ref.storage.supabase.co/storage/v1/s3",
        s3_region="eu-west-2",
        s3_access_key_id="access",
        s3_secret_access_key="secret",
    )
    store = SupabaseStorage(cfg)
    client = store._s3()
    assert client.meta.config.signature_version == "s3v4"
    assert client.meta.config.s3["addressing_style"] == "path"
    assert client.meta.config.s3["payload_signing_enabled"] is True
    assert client.meta.config.request_checksum_calculation == "when_required"
    assert client.meta.config.response_checksum_validation == "when_required"


def test_s3_probe_verifies_existing_bucket_without_writing():
    class ProbeS3(FakeS3):
        def list_objects_v2(self, Bucket, MaxKeys):
            assert Bucket == "nw-auction-private"
            assert MaxKeys == 1
            return {"KeyCount": 0}
    fake = ProbeS3()
    cfg = CloudConfig(
        bucket="nw-auction-private", s3_endpoint="https://ref.storage.supabase.co/storage/v1/s3",
        s3_region="eu-west-2", s3_access_key_id="access", s3_secret_access_key="secret"
    )
    result = SupabaseStorage(cfg, s3_client=fake).probe()
    assert result["connected"] is True
    assert result["mode"] == "s3"


def test_s3_empty_error_includes_exception_type():
    class EmptyError(Exception):
        response = {"Error": {}, "ResponseMetadata": {}}
    detail = SupabaseStorage._s3_exception_detail(EmptyError())
    assert "EmptyError" in detail
