"""S3 endpoint configuration contracts (issue #1309)."""

from __future__ import annotations

import pytest
from minio.error import S3Error

from app.core.local_backend import s3


class BucketScopedClient:
    def __init__(self, exists: bool = True, code: str = "AccessDenied") -> None:
        self.exists = exists
        self.code = code

    def list_buckets(self):
        raise S3Error(
            code=self.code,
            message="denied",
            resource="/",
            request_id="request",
            host_id="host",
            response=None,
        )

    def bucket_exists(self, bucket: str) -> bool:
        assert bucket == "apap-e2e"
        return self.exists


@pytest.mark.parametrize("endpoint", ["minio:9000", "http://minio:9000", "https://minio:9000"])
def test_endpoint_passes_bare_host_to_sdk(monkeypatch, endpoint) -> None:
    monkeypatch.setenv("APAP_S3_ENDPOINT", endpoint)
    assert s3._endpoint() == "minio:9000"


@pytest.mark.parametrize(
    ("endpoint", "secure", "expected"),
    [
        ("http://minio:9000", "true", False),
        ("https://minio:9000", "false", True),
        ("minio:9000", "false", False),
        ("minio:9000", "true", True),
    ],
)
def test_explicit_scheme_overrides_secure_setting(monkeypatch, endpoint, secure, expected) -> None:
    monkeypatch.setenv("APAP_S3_ENDPOINT", endpoint)
    monkeypatch.setenv("APAP_S3_SECURE", secure)
    assert s3._secure() is expected


def test_invalid_configured_endpoint_is_not_hidden(monkeypatch) -> None:
    monkeypatch.setenv("APAP_S3_ACCESS_KEY", "test-key")
    monkeypatch.setenv("APAP_S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("APAP_S3_ENDPOINT", "https://minio:9000/path")
    with pytest.raises(ValueError):
        s3._build_minio_client()


def test_missing_credentials_preserve_placeholder_fallback(monkeypatch) -> None:
    monkeypatch.delenv("APAP_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("APAP_S3_SECRET_KEY", raising=False)
    assert s3._build_minio_client() is None


def test_bucket_scoped_listing_returns_configured_bucket_envelope(monkeypatch) -> None:
    monkeypatch.setenv("APAP_S3_BUCKET", "apap-e2e")
    client = s3.MinioClient(BucketScopedClient())
    assert client.list_buckets() == [{"bucketName": "apap-e2e", "isPublic": False, "files": 0}]


def test_ensure_bucket_verifies_preprovisioned_bucket() -> None:
    client = s3.MinioClient(BucketScopedClient())
    assert client.ensure_bucket("apap-e2e") == {
        "bucketName": "apap-e2e",
        "isPublic": False,
        "files": 0,
    }


def test_ensure_bucket_does_not_create_missing_bucket() -> None:
    client = s3.MinioClient(BucketScopedClient(exists=False))
    with pytest.raises(ValueError, match="does not exist"):
        client.ensure_bucket("apap-e2e")


def test_bucket_listing_does_not_hide_other_s3_errors() -> None:
    client = s3.MinioClient(BucketScopedClient(code="InternalError"))
    with pytest.raises(S3Error):
        client.list_buckets()
