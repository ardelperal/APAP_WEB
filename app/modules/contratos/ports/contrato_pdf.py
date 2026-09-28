"""Transport-neutral PDF asset contract for the contratos slice (DOC-01 CP1).

Mirrors :mod:`app.modules.animals.ports.photo_asset` — same ownership
philosophy, adapted to the storage round trip this slice needs. The
dataclass is the return type of
:meth:`ContratosStoragePort.get_pdf_stream`; the CP3 delivery route
consumes it to stream a stored contract PDF back to the client.

The asset carries the object coordinates (``bucket``, ``key``), the
intrinsic media type (``application/pdf``), the optional byte length and
the raw PDF body. HTTP cache policy, validators and response headers
belong to the delivery adapter, not this port.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContratoPdf:
    """Stored contract PDF: object coordinates plus intrinsic metadata.

    ``key`` follows the legacy ``TbContratosAnexos.NombreArchivo`` naming
    convention (``{Tipo}_{entidad_id}.pdf``,
    ``docs/legacy-signed-contract-flow.md`` §"Naming en Firmados").
    ``bucket`` is the object-storage bucket the asset lives in. The
    body is the raw PDF byte string as stored; ``content_length`` is its
    byte length when the storage adapter knows it.
    """

    bucket: str
    key: str
    media_type: str = "application/pdf"
    content_length: int | None = None
    body: bytes = b""


__all__ = ["ContratoPdf"]
