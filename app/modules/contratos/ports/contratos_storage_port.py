"""Object storage port for the contratos slice (DOC-01 PR 2).

The contratos use cases depend on this Protocol for persistence of the
generated contract PDFs in object storage. The concrete adapter under
``adapters/local_backend/`` wraps MinIO; tests inject a fake that records
calls in memory so the use cases stay hermetic.

The bucket layout follows :mod:`:`docs.legacy-signed-contract-flow`
("Bucket apap-contracts + {Tipo}_{ID}.pdf"): a single private bucket
``apap-contracts`` with key names that mirror the legacy
``TbContratosAnexos.NombreArchivo`` column. The adapter is responsible
for bucket creation (``ensure_bucket``) and idempotency; the port
exposes only the document-level operations.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.contratos.ports.contrato_pdf import ContratoPDF


class ContratosStoragePort(Protocol):
    """Backend-agnostic interface for contract PDF object storage."""

    def put_pdf(self, *, bucket: str, key: str, body: bytes) -> str:
        """Store ``body`` under ``bucket/key`` and return the storage URL.

        Idempotent: storing the same ``bucket/key`` twice overwrites
        the previous body. The caller (use case) is responsible for
        the key naming convention; the adapter is responsible for
        translation to the transport's URL shape.
        """

    def get_pdf_stream(
        self, *, bucket: str, key: str
    ) -> ContratoPDF | None:
        """Return a :class:`ContratoPDF` for ``bucket/key`` or ``None``.

        Returns ``None`` when the object does not exist. The returned
        asset carries the bucket and key the caller asked for so the
        delivery route can stream the bytes back to the client.
        """

    def delete_pdf(self, *, bucket: str, key: str) -> bool:
        """Delete ``bucket/key`` and return whether the object existed.

        Returns ``True`` when the object was present and removed;
        returns ``False`` when the object was already absent (the
        delete is idempotent so retries are safe).
        """

    def list_keys(self, *, bucket: str, prefix: str = "") -> list[str]:
        """Return the keys under ``bucket`` whose name starts with ``prefix``.

        ``prefix`` defaults to ``""`` (all keys). The use case can use
        the legacy ``{Tipo}_`` prefix to enumerate every PDF for one
        contract type without fetching the bodies.
        """


__all__ = ["ContratosStoragePort"]
