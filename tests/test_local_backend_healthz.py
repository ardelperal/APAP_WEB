"""Bucket-scoped storage health contracts (issue #1309)."""

from __future__ import annotations

import pytest

from app.core.local_backend import healthz


class BucketClient:
    def __init__(self, bucket: str, exists: bool = True, error: Exception | None = None):
        self.bucket = bucket
        self.exists = exists
        self.error = error

    def bucket_exists(self, bucket: str) -> bool:
        assert bucket == self.bucket
        if self.error:
            raise self.error
        return self.exists


@pytest.fixture
def configured(monkeypatch) -> None:
    monkeypatch.setenv("APAP_S3_ACCESS_KEY", "test-key")
    monkeypatch.setenv("APAP_S3_SECRET_KEY", "test-secret")


@pytest.mark.parametrize("bucket", ["apap-photos", "apap-e2e"])
def test_health_uses_configured_bucket_not_account(monkeypatch, configured, bucket) -> None:
    monkeypatch.setenv("APAP_S3_BUCKET", bucket)
    monkeypatch.setattr(healthz, "_build_minio_client", lambda: BucketClient(bucket))
    assert healthz._storage_status() == "up"


def test_health_defaults_to_photo_bucket(monkeypatch, configured) -> None:
    monkeypatch.delenv("APAP_S3_BUCKET", raising=False)
    monkeypatch.setattr(healthz, "_build_minio_client", lambda: BucketClient("apap-photos"))
    assert healthz._storage_status() == "up"


@pytest.mark.parametrize(
    "client",
    [
        BucketClient("apap-e2e", exists=False),
        BucketClient("apap-e2e", error=OSError("unreachable")),
        None,
    ],
)
def test_configured_but_unavailable_storage_is_down(monkeypatch, configured, client) -> None:
    monkeypatch.setenv("APAP_S3_BUCKET", "apap-e2e")
    monkeypatch.setattr(healthz, "_build_minio_client", lambda: client)
    assert healthz._storage_status() == "down"


def test_absent_credentials_are_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("APAP_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("APAP_S3_SECRET_KEY", raising=False)
    assert healthz._storage_status() == "unconfigured"
