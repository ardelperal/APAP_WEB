"""MinIO-backed storage adapter for the contratos slice (DOC-01 CP4, #850).

Implements the CP1 ``ContratosStoragePort`` on top of the S3-compatible
MinIO client the LocalBackend already wires (``app.core.local_backend.s3``).
ONLY module in the slice allowed to import ``minio`` (AGENTS.md §33.4
pin test). Constructor-injected client (animals-photo DI pattern): no
network, no credentials, no global getter. Tests inject an in-memory
fake with real-client semantics: missing-key ``get_object`` /
``stat_object`` raise ``S3Error(code="NoSuchKey")``; ``remove_object``
is idempotent, so delete stats before removing. Only ``NoSuchKey`` is
translated (missing object → ``None`` / ``False`` per the CP1 port
contract); any other S3 error propagates to the caller.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Protocol

from minio.error import S3Error

from app.modules.contratos.ports.contrato_pdf import ContratoPdf

#: Default private bucket, mirroring the legacy naming in
#: ``docs/legacy-signed-contract-flow.md`` ("apap-contracts + {Tipo}_{ID}.pdf").
DEFAULT_BUCKET = "apap-contracts"

#: Chunk size used to consume the get-object response body; matches the
#: streaming chunk size of the animals photo pipeline.
_CHUNK_SIZE = 8192


class _GetObjectResponse(Protocol):
    """Minimal shape of the response ``get_object`` returns."""

    def stream(self, chunk_size: int) -> Iterator[bytes]: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class S3StorageClient(Protocol):
    """Minimal real storage API the adapter needs from ``minio.Minio``."""

    def put_object(
        self,
        bucket: str,
        key: str,
        data: io.BytesIO,
        length: int,
        content_type: str | None = None,
    ) -> None: ...

    def get_object(self, bucket: str, key: str) -> _GetObjectResponse: ...

    def stat_object(self, bucket: str, key: str) -> object: ...

    def remove_object(self, bucket: str, key: str) -> None: ...


class MinioContratosStorage:
    """Concrete :class:`ContratosStoragePort` backed by MinIO / S3."""

    def __init__(self, client: S3StorageClient) -> None:
        self._client = client

    def put_pdf(self, *, bucket: str, key: str, body: bytes) -> str:
        """Store ``body`` under ``bucket/key`` and return ``{bucket}/{key}``.

        Idempotent: storing the same coordinates twice overwrites the
        previous body (last write wins). The upload always declares
        ``application/pdf`` — the only media type the slice produces.
        """
        self._client.put_object(
            bucket,
            key,
            io.BytesIO(body),
            len(body),
            content_type="application/pdf",
        )
        return f"{bucket}/{key}"

    def get_pdf_stream(self, *, bucket: str, key: str) -> ContratoPdf | None:
        """Return a :class:`ContratoPdf` for ``bucket/key`` or ``None``.

        The response body is consumed in fixed-size chunks and
        reassembled; the connection is released even when reading
        fails. ``None`` only for a missing object (``NoSuchKey``).
        """
        try:
            response = self._client.get_object(bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return None
            raise
        try:
            chunks = list(response.stream(_CHUNK_SIZE))
        finally:
            response.close()
            response.release_conn()
        body = b"".join(chunks)
        return ContratoPdf(
            bucket=bucket,
            key=key,
            media_type="application/pdf",
            content_length=len(body),
            body=body,
        )

    def delete_pdf(self, *, bucket: str, key: str) -> bool:
        """Delete ``bucket/key`` and return whether the object existed.

        S3 deletes never report absence, so the adapter stats first:
        ``NoSuchKey`` → ``False``; a present object is removed → ``True``.
        """
        try:
            self._client.stat_object(bucket, key)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise
        self._client.remove_object(bucket, key)
        return True


__all__ = ["DEFAULT_BUCKET", "MinioContratosStorage"]
