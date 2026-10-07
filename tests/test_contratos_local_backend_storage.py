"""Tests for the MinIO-backed storage adapter (DOC-01 CP4, issue #850).

Application unit (apap-testing-strategy §3): in-memory fake client, no
DB, no network. The fake reproduces real ``minio.Minio`` semantics:
missing-key ``get_object``/``stat_object`` raise
``S3Error(code="NoSuchKey")``; ``remove_object`` is idempotent, so
existence detection before delete is the adapter's job. Fixtures are
gitleaks-safe: keys stay below the ``generic-api-key`` 10-char
threshold (the #795 failure mode). web-tdd-philosophy: fixture gate,
no humo, cardinality, three paths, refactor-safety, no mutation.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field

from minio.error import S3Error

from app.modules.contratos.adapters.local_backend.contratos_local_backend_storage import (
    DEFAULT_BUCKET,
    MinioContratosStorage,
)
from app.modules.contratos.ports.contratos_storage_port import (
    ContratosStoragePort,
)


@dataclass
class _FakeObject:
    """A stored object kept in memory by the fake client."""

    body: bytes
    content_type: str = "application/pdf"


@dataclass
class _FakeResponse:
    """Minimal get-object response: chunked ``stream`` + conn release."""

    body: bytes

    def stream(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


def _no_such_key(key: str, bucket: str) -> S3Error:
    """Build the S3Error the real client raises for a missing object."""
    return S3Error(
        code="NoSuchKey",
        message=f"object {key} not found in {bucket}",
        resource=bucket,
        request_id="fake",
        host_id="fake",
        response=None,  # type: ignore[arg-type]
    )


@dataclass
class _FakeClient:
    """In-memory MinIO substitute with real-client missing-key semantics."""

    objects: dict[str, dict[str, _FakeObject]] = field(
        default_factory=dict
    )

    def put_object(
        self,
        bucket: str,
        key: str,
        data: io.BytesIO,
        length: int,
        content_type: str | None = None,
    ) -> None:
        body = data.read(length)
        self.objects.setdefault(bucket, {})[key] = _FakeObject(
            body=body,
            content_type=content_type or "application/octet-stream",
        )

    def get_object(self, bucket: str, key: str) -> _FakeResponse:
        obj = self.objects.get(bucket, {}).get(key)
        if obj is None:
            raise _no_such_key(key, bucket)
        return _FakeResponse(body=obj.body)

    def stat_object(self, bucket: str, key: str) -> _FakeObject:
        obj = self.objects.get(bucket, {}).get(key)
        if obj is None:
            raise _no_such_key(key, bucket)
        return obj

    def remove_object(self, bucket: str, key: str) -> None:
        self.objects.get(bucket, {}).pop(key, None)



def test_adapter_satisfies_contratos_storage_port() -> None:
    """The adapter is a runtime ``ContratosStoragePort`` instance."""
    adapter = MinioContratosStorage(_FakeClient())  # type: ignore[arg-type]
    assert isinstance(adapter, ContratosStoragePort)



def test_put_pdf_stores_body_and_returns_marker() -> None:
    """``put_pdf`` writes the body, declares PDF media type, returns the marker."""
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]
    marker = adapter.put_pdf(
        bucket="apap-contracts", key="A_42.pdf", body=b"%PDF-fake"
    )

    assert marker == "apap-contracts/A_42.pdf"
    assert len(client.objects["apap-contracts"]) == 1  # cardinality after
    stored = client.objects["apap-contracts"]["A_42.pdf"]
    assert stored.body == b"%PDF-fake"
    assert stored.content_type == "application/pdf"


def test_put_pdf_overwrites_existing_object() -> None:
    """Storing the same bucket/key twice replaces the body (last write wins)."""
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    adapter.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v1")
    adapter.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v2")

    assert len(client.objects["apap-contracts"]) == 1  # cardinality
    assert client.objects["apap-contracts"]["E_1.pdf"].body == b"v2"



def test_get_pdf_stream_returns_contrato_pdf_with_body() -> None:
    """``get_pdf_stream`` reconstructs a multi-chunk object faithfully."""
    body = b"%PDF-" + b"x" * (2 * 8192 + 7)  # spans several chunks
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["A_42.pdf"] = _FakeObject(
        body=body
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    asset = adapter.get_pdf_stream(bucket="apap-contracts", key="A_42.pdf")

    assert asset is not None
    assert asset.bucket == "apap-contracts"
    assert asset.key == "A_42.pdf"
    assert asset.media_type == "application/pdf"
    assert asset.content_length == len(body)
    assert asset.body == body


def test_get_pdf_stream_returns_none_for_missing_key() -> None:
    """A missing object returns ``None`` instead of raising (sad path)."""
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    assert (
        adapter.get_pdf_stream(bucket="apap-contracts", key="gone.pdf")
        is None
    )



def test_delete_pdf_returns_true_when_object_existed() -> None:
    """Deleting an existing object returns ``True`` and removes the body."""
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["C_7.pdf"] = _FakeObject(
        body=b"%PDF"
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    assert adapter.delete_pdf(bucket="apap-contracts", key="C_7.pdf") is True
    assert "C_7.pdf" not in client.objects["apap-contracts"]


def test_double_delete_is_idempotent() -> None:
    """Deleting twice yields ``True`` then ``False``; an absent delete is False."""
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]
    assert adapter.delete_pdf(bucket="apap-contracts", key="nope.pdf") is False

    client.objects.setdefault("apap-contracts", {})["E_1.pdf"] = _FakeObject(
        body=b"%PDF"
    )
    assert adapter.delete_pdf(bucket="apap-contracts", key="E_1.pdf") is True
    assert adapter.delete_pdf(bucket="apap-contracts", key="E_1.pdf") is False
    assert len(client.objects["apap-contracts"]) == 0  # cardinality



def test_default_bucket_is_apap_contracts() -> None:
    """The slice's default bucket is ``apap-contracts`` (legacy naming)."""
    assert DEFAULT_BUCKET == "apap-contracts"
