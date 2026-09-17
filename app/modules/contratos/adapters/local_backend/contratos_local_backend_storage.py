"""Object storage adapter for the contratos slice (DOC-01 PR 2, #56).

The :class:`ContratosStoragePort` Protocol in
``ports/contratos_storage_port.py`` is implemented here against a MinIO
client (S3-compatible). The adapter is the only module in the slice
allowed to import ``minio`` or ``app.core.local_backend``; the pin
arquitectónico fails immediately when such an import leaks into
``domain/``, ``ports/`` or ``application/``.

Bucket layout mirrors the legacy ``TbContratosAnexos.NombreArchivo``
naming convention (``docs/legacy-signed-contract-flow.md``):
``apap-contracts`` bucket, private (``isPublic=false``), key
``{Tipo}_{entidad_id}.pdf``. Bucket creation is the operator's
responsibility (``app.core.local_backend.storage.ensure_bucket``);
this adapter only writes and reads documents.

The adapter returns storage markers (``{bucket}/{key}``) from
:meth:`put_pdf` rather than presigned URLs because the bucket is
private; the future delivery route (PR 3) will resolve the marker to
an authorised streaming response, never to a public URL.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import TYPE_CHECKING

from minio.error import S3Error

from app.modules.contratos.ports.contrato_pdf import (
    ContratoPDF,
)

if TYPE_CHECKING:
    from minio import Minio


#: Default bucket name for the contratos slice. Matches the legacy
#: :class:`docs.legacy-signed-contract-flow` §"Naming en Firmados"
#: convention and is private (``isPublic=false``) per P1.
DEFAULT_BUCKET = "apap-contracts"

#: Default chunk size for streaming responses (8 KiB).
_CHUNK_SIZE = 8 * 1024


class _MinioBytesIterator:
    """Wrap a MinIO ``get_object`` response into a :class:`ClosableBytesIterator`.

    reportlab / route handlers consume the stream through ``__next__``
    and call ``close()`` when finished. MinIO's response object
    exposes ``stream(chunk_size)`` plus ``close()`` and ``release_conn()``;
    this wrapper delegates both and shields callers from the
    transport shape.
    """

    def __init__(self, response: object) -> None:
        self._response = response
        self._stream: Iterator[bytes] | None = None
        self._closed = False

    def __iter__(self) -> _MinioBytesIterator:
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        if self._stream is None:
            self._stream = iter(self._response.stream(_CHUNK_SIZE))  # type: ignore[attr-defined]
        try:
            chunk = next(self._stream)
        except StopIteration:
            self.close()
            raise
        return chunk

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._response, "close", None)
        if callable(close):
            close()
        release_conn = getattr(self._response, "release_conn", None)
        if callable(release_conn):
            release_conn()


class MinioContratosStorage:
    """MinIO-backed implementation of :class:`ContratosStoragePort`.

    The ``client`` is the shared MinIO connection from
    :mod:`:`app.core.local_backend.s3` (or a test double). Bucket
    creation is NOT this adapter's job — the operator pre-creates
    ``apap-contracts`` via ``ensure_bucket`` and the slice only writes
    documents.
    """

    def __init__(self, client: Minio) -> None:
        self._client = client

    def put_pdf(self, *, bucket: str, key: str, body: bytes) -> str:
        """Store ``body`` under ``bucket/key`` and return the storage marker.

        The marker shape is ``{bucket}/{key}`` and is resolved to an
        authorised streaming response by the future delivery route
        (PR 3). Idempotent: storing the same key twice overwrites the
        previous body — MinIO's ``put_object`` semantics.
        """
        stream = io.BytesIO(body)
        self._client.put_object(
            bucket,
            key,
            stream,
            length=len(body),
            content_type="application/pdf",
        )
        return f"{bucket}/{key}"

    def get_pdf_stream(
        self, *, bucket: str, key: str
    ) -> ContratoPDF | None:
        """Return a :class:`ContratoPDF` for ``bucket/key`` or ``None``.

        ``None`` is returned only when MinIO reports ``NoSuchKey``;
        any other transport error propagates so the route handler can
        translate it into a 5xx response.
        """
        try:
            response = self._client.get_object(bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise
        return ContratoPDF(
            stream=_MinioBytesIterator(response),
            media_type="application/pdf",
            content_length=_safe_content_length(response),
            key=key,
            bucket=bucket,
        )

    def delete_pdf(self, *, bucket: str, key: str) -> bool:
        """Delete ``bucket/key`` and return whether the object existed.

        Idempotent: removing an already-absent object returns
        ``False`` without raising. Other transport errors propagate.
        """
        try:
            self._client.remove_object(bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise
        return True

    def list_keys(self, *, bucket: str, prefix: str = "") -> list[str]:
        """Return the keys under ``bucket`` whose name starts with ``prefix``.

        ``prefix`` defaults to ``""`` (all keys). The use case can use
        the legacy ``{Tipo}_`` prefix to enumerate every PDF for one
        contract type without fetching the bodies.
        """
        objects = list(self._client.list_objects(bucket, prefix=prefix))
        return [obj.object_name for obj in objects]


def _safe_content_length(response: object) -> int | None:
    """Best-effort content-length extraction from a MinIO response.

    MinIO's response objects expose size metadata in several shapes
    (``headers['Content-Length']`` or ``stats.size``); this helper
    returns the first one it can find and ``None`` otherwise. The
    delivery route (PR 3) uses ``None`` to skip the
    ``Content-Length`` header on the response.
    """
    headers = getattr(response, "headers", None)
    if headers is not None:
        length = headers.get("Content-Length") or headers.get(
            "content-length"
        )
        if length is not None:
            try:
                return int(length)
            except (TypeError, ValueError):
                pass
    stats = getattr(response, "stats", None)
    if stats is not None:
        size = getattr(stats, "size", None)
        if isinstance(size, int):
            return size
    return None


__all__ = ["DEFAULT_BUCKET", "MinioContratosStorage"]
