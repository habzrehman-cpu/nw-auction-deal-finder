"""Optional private Supabase persistence for the Streamlit deployment.

The application remains SQLite-first so local development is simple. For the current
single-user Community Cloud deployment, the SQLite database is snapshotted to private
Supabase Storage and restored after a cold start. User-uploaded legal originals can be
stored in the same private bucket.

Preferred authentication is Supabase Storage's S3-compatible server credentials.
A REST secret/service-role fallback is retained for backwards compatibility.
This is a pragmatic single-user persistence layer, not a concurrent multi-user DB.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import mimetypes
import os
import re
import tempfile
from urllib.parse import quote

import requests


@dataclass
class CloudConfig:
    bucket: str = "nw-auction-private"
    database_object: str = "state/auction_tracker.db"
    # Preferred S3-compatible Supabase Storage credentials.
    s3_endpoint: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Optional REST fallback.
    url: str = ""
    secret_key: str = ""

    @property
    def s3_configured(self) -> bool:
        return bool(self.bucket and self.s3_endpoint and self.s3_region and self.s3_access_key_id and self.s3_secret_access_key)

    @property
    def rest_configured(self) -> bool:
        return bool(self.bucket and self.url and self.secret_key)

    @property
    def configured(self) -> bool:
        return self.s3_configured or self.rest_configured


class SupabaseStorage:
    """Private Storage wrapper supporting Supabase S3 or REST server credentials."""

    def __init__(self, config: CloudConfig, session=None, s3_client=None):
        self.config = config
        self.session = session or requests.Session()
        self.base = config.url.rstrip("/")
        self._s3_client = s3_client

    @property
    def configured(self):
        return self.config.configured

    @property
    def mode(self):
        return "s3" if self.config.s3_configured else "rest" if self.config.rest_configured else "none"

    def _s3(self):
        if not self.config.s3_configured:
            return None
        if self._s3_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("boto3 is required for Supabase S3 persistence") from exc
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.config.s3_endpoint,
                region_name=self.config.s3_region,
                aws_access_key_id=self.config.s3_access_key_id,
                aws_secret_access_key=self.config.s3_secret_access_key,
                config=__import__("botocore.config", fromlist=["Config"]).Config(s3={"addressing_style": "path"}),
            )
        return self._s3_client

    def _headers(self, content_type=None):
        headers = {
            "apikey": self.config.secret_key,
            "User-Agent": "NW-Auction-Deal-Finder/1.8 server",
        }
        # New sb_secret_* API keys are API keys, not JWTs. Legacy service_role JWTs
        # may additionally be used as a Bearer token by Storage's authenticated route.
        if self.config.secret_key and not str(self.config.secret_key).startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.config.secret_key}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def ensure_bucket(self):
        if not self.configured:
            return False
        if self.mode == "s3":
            client = self._s3()
            try:
                client.head_bucket(Bucket=self.config.bucket)
            except Exception:
                client.create_bucket(Bucket=self.config.bucket)
            return True
        bucket = quote(self.config.bucket, safe="")
        r = self.session.get(f"{self.base}/storage/v1/bucket/{bucket}", headers=self._headers(), timeout=20)
        if r.status_code == 200:
            return True
        if r.status_code not in {400, 404}:
            r.raise_for_status()
        create = self.session.post(
            f"{self.base}/storage/v1/bucket",
            headers=self._headers("application/json"),
            json={"id": self.config.bucket, "name": self.config.bucket, "public": False},
            timeout=20,
        )
        if create.status_code not in {200, 201, 400, 409}:
            create.raise_for_status()
        return True

    def _object_url(self, path: str, authenticated=False):
        encoded = "/".join(quote(part, safe="") for part in path.strip("/").split("/"))
        prefix = "authenticated/" if authenticated else ""
        return f"{self.base}/storage/v1/object/{prefix}{quote(self.config.bucket, safe='')}/{encoded}"

    def download_bytes(self, path: str) -> bytes | None:
        if not self.configured:
            return None
        if self.mode == "s3":
            try:
                obj = self._s3().get_object(Bucket=self.config.bucket, Key=path)
                return obj["Body"].read()
            except Exception as exc:
                response = getattr(exc, "response", {}) or {}
                code = str((response.get("Error") or {}).get("Code") or "")
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return None
                raise
        r = self.session.get(self._object_url(path, authenticated=True), headers=self._headers(), timeout=45)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def upload_bytes(self, path: str, data: bytes, content_type="application/octet-stream") -> str:
        if not self.configured:
            raise RuntimeError("Supabase persistence is not configured")
        self.ensure_bucket()
        if self.mode == "s3":
            self._s3().put_object(Bucket=self.config.bucket, Key=path, Body=data, ContentType=content_type)
            return path
        headers = self._headers(content_type)
        headers["x-upsert"] = "true"
        r = self.session.post(self._object_url(path), headers=headers, data=data, timeout=60)
        if r.status_code not in {200, 201}:
            r = self.session.put(self._object_url(path), headers=headers, data=data, timeout=60)
        r.raise_for_status()
        return path

    def restore_database_if_missing(self, local_path: str | Path) -> dict:
        local_path = Path(local_path)
        if local_path.exists() or not self.configured:
            return {"restored": False, "reason": "local-present" if local_path.exists() else "not-configured"}
        self.ensure_bucket()
        data = self.download_bytes(self.config.database_object)
        if not data:
            return {"restored": False, "reason": "no-remote-snapshot"}
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=local_path.parent, delete=False) as tmp:
            tmp.write(data)
            temp_name = tmp.name
        os.replace(temp_name, local_path)
        return {"restored": True, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def upload_database(self, local_path: str | Path) -> dict:
        local_path = Path(local_path)
        if not self.configured:
            return {"synced": False, "reason": "not-configured"}
        if not local_path.exists():
            return {"synced": False, "reason": "database-missing"}
        data = local_path.read_bytes()
        self.upload_bytes(self.config.database_object, data, "application/x-sqlite3")
        return {"synced": True, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    @staticmethod
    def safe_name(name: str) -> str:
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "document")).strip("-.")
        return name[:160] or "document"

    def legal_object_path(self, property_id: int, sha256: str, filename: str) -> str:
        stem = self.safe_name(filename)
        return f"legal-packs/{int(property_id)}/{sha256[:16]}-{stem}"

    def upload_legal_document(self, property_id: int, filename: str, data: bytes, sha256: str) -> str:
        path = self.legal_object_path(property_id, sha256, filename)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return self.upload_bytes(path, data, ctype)


def config_from_mapping(mapping) -> CloudConfig:
    """Build config from Streamlit Secrets, env vars, or a dict-like object."""
    section = {}
    try:
        if mapping is not None:
            section = mapping.get("supabase", {}) or {}
    except Exception:
        section = {}

    def pick(*names, default=""):
        for name in names:
            value = None
            try:
                value = section.get(name)
            except Exception:
                value = None
            value = value or os.environ.get(name.upper())
            if value:
                return str(value)
        return default

    return CloudConfig(
        bucket=pick("bucket", default="nw-auction-private"),
        database_object=pick("database_object", default="state/auction_tracker.db"),
        s3_endpoint=pick("s3_endpoint", default=os.environ.get("SUPABASE_S3_ENDPOINT", "")),
        s3_region=pick("s3_region", default=os.environ.get("SUPABASE_S3_REGION", "")),
        s3_access_key_id=pick("s3_access_key_id", default=os.environ.get("SUPABASE_S3_ACCESS_KEY_ID", "")),
        s3_secret_access_key=pick("s3_secret_access_key", default=os.environ.get("SUPABASE_S3_SECRET_ACCESS_KEY", "")),
        url=pick("url", "supabase_url", default=os.environ.get("SUPABASE_URL", "")),
        secret_key=pick("secret_key", "service_role_key", default=os.environ.get("SUPABASE_SECRET_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")),
    )
