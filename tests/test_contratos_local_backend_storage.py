"""Tests for the MinIO-backed storage adapter (DOC-01 PR 2).

The adapter is the only module in the slice allowed to import
``minio``. Tests run against an in-memory fake client so they stay
hermetic and never touch the real MinIO endpoint.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): the fake client is plain Python, no I/O.
- Rule 2 (no humo): every assertion pins one observable contract —
  the stored body, the returned iterator, the ``NoSuchKey`` mapping.
- Rule 4 (no production mutation): the tests exercise the public
  :class:`MinioContratosStorage` surface only.
- Rule 8 (no production mutation): no fixtures hit a database.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from minio.error import S3Error

from app.modules.contratos.adapters.local_backend.contratos_local_backend_storage import (
    DEFAULT_BUCKET,
    MinioContratosStorage,
)
from app.modules.contratos.ports.contrato_pdf import ContratoPDF

# --- 1. Fake MinIO client --------------------------------------------------


@dataclass
class _FakeObject:
    """A stored object kept in memory by the fake client."""

    body: bytes
    content_type: str = "application/pdf"


@dataclass
class _FakeResponse:
    """A minimal get-object response shape.

    The adapter wraps this in ``_MinioBytesIterator`` so the
    ``stream(chunk_size)`` method yields the bytes in fixed chunks.
    """

    body: bytes

    def stream(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:  # noqa: D401 — protocol-compatible
        return None

    def release_conn(self) -> None:  # noqa: D401 — protocol-compatible
        return None

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Length": str(len(self.body))}


@dataclass
class _FakeClient:
    """In-memory MinIO substitute.

    Stores ``{bucket: {key: _FakeObject}}`` and implements the four
    methods the adapter calls. The ``raise_on_get`` /
    ``raise_on_remove`` flags inject a ``S3Error`` so the
    ``NoSuchKey`` mapping is testable.
    """

    objects: dict[str, dict[str, _FakeObject]] = field(default_factory=dict)
    raise_on_get: tuple[str, str] | None = None
    raise_on_remove: tuple[str, str] | None = None
    put_calls: list[dict[str, Any]] = field(default_factory=list)

    def put_object(
        self,
        bucket: str,
        key: str,
        data: io.BytesIO,
        length: int,
        content_type: str | None = None,
    ) -> None:
        body = data.read(length)
        self.put_calls.append(
            {
                "bucket": bucket,
                "key": key,
                "length": length,
                "content_type": content_type,
            }
        )
        self.objects.setdefault(bucket, {})[key] = _FakeObject(
            body=body,
            content_type=content_type or "application/octet-stream",
        )

    def get_object(self, bucket: str, key: str) -> _FakeResponse:
        if self.raise_on_get is not None:
            raise_b, raise_k = self.raise_on_get
            if raise_b == bucket and raise_k == key:
                raise S3Error(
                    code="NoSuchKey",
                    message=f"object {key} not found in {bucket}",
                    resource=bucket,
                    request_id="fake",
                    host_id="fake",
                    response=None,  # type: ignore[arg-type]
                )
        bucket_objs = self.objects.get(bucket, {})
        obj = bucket_objs.get(key)
        if obj is None:
            raise S3Error(
                code="NoSuchKey",
                message=f"object {key} not found in {bucket}",
                resource=bucket,
                request_id="fake",
                host_id="fake",
                response=None,  # type: ignore[arg-type]
            )
        return _FakeResponse(body=obj.body)

    def remove_object(self, bucket: str, key: str) -> None:
        if self.raise_on_remove is not None:
            raise_b, raise_k = self.raise_on_remove
            if raise_b == bucket and raise_k == key:
                raise S3Error(
                    code="NoSuchKey",
                    message=f"object {key} not found in {bucket}",
                    resource=bucket,
                    request_id="fake",
                    host_id="fake",
                    response=None,  # type: ignore[arg-type]
                )
        bucket_objs = self.objects.get(bucket, {})
        if key not in bucket_objs:
            # MinIO's real client raises NoSuchKey when the target key
            # is absent; mimic that so the adapter's idempotent-delete
            # contract is exercised end-to-end.
            raise S3Error(
                code="NoSuchKey",
                message=f"object {key} not found in {bucket}",
                resource=bucket,
                request_id="fake",
                host_id="fake",
                response=None,  # type: ignore[arg-type]
            )
        bucket_objs.pop(key, None)

    def list_objects(self, bucket: str, prefix: str = "") -> list[Any]:
        bucket_objs = self.objects.get(bucket, {})

        class _ListedObject:
            def __init__(self, object_name: str) -> None:
                self.object_name = object_name

        return [
            _ListedObject(name)
            for name in sorted(bucket_objs.keys())
            if name.startswith(prefix)
        ]


# --- 2. put / get / delete round-trip -------------------------------------


def test_put_pdf_stores_body_and_returns_marker() -> None:
    """``put_pdf`` writes the body and returns ``{bucket}/{key}``.

    The marker is the future delivery route's lookup key. Pins the
    shape so PR 3 can rely on it.
    """
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    marker = adapter.put_pdf(
        bucket="apap-contracts",
        key="Adopcion_42.pdf",
        body=b"%PDF-fake",
    )
    assert marker == "apap-contracts/Adopcion_42.pdf"
    assert client.objects["apap-contracts"]["Adopcion_42.pdf"].body == b"%PDF-fake"


def test_put_pdf_overwrites_existing_object() -> None:
    """Storing the same key twice replaces the body.

    The legacy semantics allow replacement with confirmation (see
    ``docs/legacy-signed-contract-flow.md`` §"Reemplazo"); the
    adapter mirrors that by overwriting the previous body.
    """
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    adapter.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v1")
    adapter.put_pdf(bucket="apap-contracts", key="E_1.pdf", body=b"v2")
    assert client.objects["apap-contracts"]["E_1.pdf"].body == b"v2"


def test_get_pdf_stream_returns_contratopdf_with_stream() -> None:
    """``get_pdf_stream`` returns a ``ContratoPDF`` with a readable stream.

    Pins the public shape: the returned dataclass carries
    ``stream``, ``media_type``, ``key`` and ``bucket``; the stream
    yields the stored body in chunks.
    """
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["Adopcion_42.pdf"] = (
        _FakeObject(body=b"%PDF-stored")
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    asset = adapter.get_pdf_stream(
        bucket="apap-contracts", key="Adopcion_42.pdf"
    )
    assert isinstance(asset, ContratoPDF)
    assert asset.bucket == "apap-contracts"
    assert asset.key == "Adopcion_42.pdf"
    assert asset.media_type == "application/pdf"
    assert asset.content_length == len(b"%PDF-stored")
    chunks = list(iter(asset.stream))
    assert b"".join(chunks) == b"%PDF-stored"
    asset.stream.close()


def test_get_pdf_stream_returns_none_for_missing_key() -> None:
    """A missing object returns ``None`` instead of raising.

    The route handler (PR 3) translates ``None`` into a 404; any
    other S3 error propagates so the caller can map it to 5xx.
    """
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]
    assert (
        adapter.get_pdf_stream(bucket="apap-contracts", key="missing.pdf")
        is None
    )


def test_delete_pdf_returns_true_when_object_existed() -> None:
    """Deleting an existing object returns ``True`` and removes the body."""
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["Acogida_7.pdf"] = (
        _FakeObject(body=b"%PDF")
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    assert (
        adapter.delete_pdf(bucket="apap-contracts", key="Acogida_7.pdf")
        is True
    )
    assert "Acogida_7.pdf" not in client.objects["apap-contracts"]


def test_delete_pdf_returns_false_when_object_absent() -> None:
    """Deleting an absent object is idempotent — returns ``False``.

    Pins the retry-safe semantics: a second delete after the first
    succeeds does not raise.
    """
    client = _FakeClient()
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]
    assert (
        adapter.delete_pdf(bucket="apap-contracts", key="nope.pdf")
        is False
    )


def test_list_keys_filters_by_prefix() -> None:
    """``list_keys`` returns the keys matching the prefix only."""
    client = _FakeClient()
    client.objects["apap-contracts"] = {
        "Adopcion_1.pdf": _FakeObject(body=b"a"),
        "Adopcion_2.pdf": _FakeObject(body=b"b"),
        "Acogida_1.pdf": _FakeObject(body=b"c"),
    }
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    keys = adapter.list_keys(bucket="apap-contracts", prefix="Adopcion_")
    assert keys == ["Adopcion_1.pdf", "Adopcion_2.pdf"]


def test_list_keys_without_prefix_returns_all() -> None:
    """``list_keys`` with an empty prefix returns every key in the bucket."""
    client = _FakeClient()
    client.objects["apap-contracts"] = {
        "Adopcion_1.pdf": _FakeObject(body=b"a"),
        "Acogida_1.pdf": _FakeObject(body=b"b"),
    }
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    keys = adapter.list_keys(bucket="apap-contracts")
    assert sorted(keys) == ["Acogida_1.pdf", "Adopcion_1.pdf"]


# --- 3. Default bucket constant ------------------------------------------


def test_default_bucket_is_apap_contracts() -> None:
    """The slice's default bucket is ``apap-contracts``.

    Pins the constant so PR 3's route handler can rely on the
    legacy-compatible naming.
    """
    assert DEFAULT_BUCKET == "apap-contracts"


# --- 4. Stream ownership contract ----------------------------------------


def test_get_pdf_stream_stream_is_closable() -> None:
    """``ContratoPDF.stream.close()`` is a no-op on already-closed streams.

    Pins the idempotent close contract that the delivery route
    relies on for cleanup determinism.
    """
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["X.pdf"] = _FakeObject(
        body=b"%PDF"
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    asset = adapter.get_pdf_stream(bucket="apap-contracts", key="X.pdf")
    assert asset is not None
    asset.stream.close()
    asset.stream.close()  # second close must not raise


# --- 5. Stream iteration past EOF ----------------------------------------


def test_get_pdf_stream_raises_stopiteration_after_consumption() -> None:
    """Iterating past EOF raises ``StopIteration`` and closes the stream.

    The ``_MinioBytesIterator`` must auto-close when the underlying
    stream is exhausted so the delivery route's cleanup path runs
    deterministically even on partial consumption.
    """
    client = _FakeClient()
    client.objects.setdefault("apap-contracts", {})["Y.pdf"] = _FakeObject(
        body=b"short"
    )
    adapter = MinioContratosStorage(client)  # type: ignore[arg-type]

    asset = adapter.get_pdf_stream(bucket="apap-contracts", key="Y.pdf")
    assert asset is not None
    iterator = iter(asset.stream)
    chunks = list(iterator)
    assert b"".join(chunks) == b"short"
    with pytest.raises(StopIteration):
        next(iterator)
