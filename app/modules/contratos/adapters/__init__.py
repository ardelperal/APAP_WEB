"""Contracts slice: DOC-01 (#56) — transport adapters.

The modules under this package are the only layer allowed to import
transport (weasyprint, reportlab, MinIO, SQL). Domain, ports and
application code stay transport-free by depending on the Protocols in
``ports/`` only.

Mirrors :mod:`:`app.modules.animals.adapters`: one folder per
transport. Today only ``local_backend/`` exists; future transports
(s3 direct, gcs) would land as siblings.
"""

from __future__ import annotations

__all__: list[str] = []
