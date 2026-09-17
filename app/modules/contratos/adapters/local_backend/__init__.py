"""LocalBackend adapter surface for the contratos slice (DOC-01 PR 2).

The modules under this package implement the Protocols declared in
``app/modules/contratos/ports/`` against the local Coolify stack:

- :mod:`contratos_local_backend_pdf` — PDF generation via reportlab.
- :mod:`contratos_local_backend_storage` — object storage via MinIO.

These are the only modules in the slice allowed to import
``reportlab``, ``minio`` or ``app.core.local_backend``. The pin
architectónico test fails immediately when such an import leaks into
``domain/``, ``ports/`` or ``application/``.
"""

from __future__ import annotations

__all__: list[str] = []
