"""Transport-neutral PDF asset contract for the contratos slice (DOC-01 PR 2).

Mirrors :mod:`:`app.modules.animals.ports.photo_asset` — same shape, same
ownership contract. The dataclass is the return type of
:class:`ContratosStoragePort.get_pdf_stream`; the iterator protocol is the
typed stream the route handler (PR 3) will consume to deliver the PDF.

The PDF stream carries intrinsic media type (``application/pdf``) and
optional byte length only. HTTP cache policy, validators and response
headers belong to the future delivery adapter, not this port.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ClosableBytesIterator(Protocol):
    """Owned byte stream that callers must close after consumption."""

    def __iter__(self) -> ClosableBytesIterator: ...

    def __next__(self) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ContratoPDF:
    """Resolved PDF bytes and intrinsic asset metadata.

    ``stream`` owns the underlying storage resource. The consumer must
    call ``close()`` in deterministic cleanup, including cancellation and
    partial-consumption paths.

    ``key`` follows the legacy ``TbContratosAnexos.NombreArchivo``
    naming convention (``{Tipo}_{entidad_id}.pdf``,
    ``docs/legacy-signed-contract-flow.md`` §"Naming en Firmados").
    ``bucket`` is the object-storage bucket the asset lives in; PR 3's
    delivery route will use it to construct the storage lookup.
    """

    stream: ClosableBytesIterator
    media_type: str
    content_length: int | None
    key: str
    bucket: str


__all__ = ["ClosableBytesIterator", "ContratoPDF"]
