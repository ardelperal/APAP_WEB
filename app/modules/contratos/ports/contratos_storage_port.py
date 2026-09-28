"""Object storage port for the contratos slice (DOC-01 CP1, issue #850).

The contratos use cases depend on this Protocol for persistence of the
generated contract PDFs in object storage. The concrete adapter under
``adapters/local_backend/`` (CP4) wraps the S3-compatible client; tests
inject a fake that records calls in memory so the use cases stay
hermetic.

The bucket layout follows ``docs/legacy-signed-contract-flow.md``
("Bucket apap-contracts + {Tipo}_{ID}.pdf"): a single private bucket
with key names that mirror the legacy ``TbContratosAnexos.NombreArchivo``
column. The adapter is responsible for bucket provisioning and
idempotency; the port exposes only the document-level operations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.contratos.ports.contrato_pdf import ContratoPdf


@runtime_checkable
class ContratosStoragePort(Protocol):
    """Backend-agnostic interface for contract PDF object storage."""

    def put_pdf(self, *, bucket: str, key: str, body: bytes) -> str:
        """Store ``body`` under ``bucket/key`` and return the storage marker.

        Idempotent: storing the same ``bucket/key`` twice overwrites
        the previous body. The caller (use case) is responsible for the
        key naming convention; the adapter is responsible for
        translation to the transport's marker shape.
        """

    def get_pdf_stream(self, *, bucket: str, key: str) -> ContratoPdf | None:
        """Return a :class:`ContratoPdf` for ``bucket/key`` or ``None``.

        Returns ``None`` when the object does not exist — the delivery
        route (CP3) translates that into a 404. The returned asset
        carries the bucket and key the caller asked for so the route
        can serve the bytes back to the client.
        """

    def delete_pdf(self, *, bucket: str, key: str) -> bool:
        """Delete ``bucket/key`` and return whether the object existed.

        Returns ``True`` when the object was present and removed;
        returns ``False`` when the object was already absent (the
        delete is idempotent so retries are safe).
        """


__all__ = ["ContratosStoragePort"]
