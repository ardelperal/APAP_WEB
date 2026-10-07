"""Filesystem adapters for the contratos slice (DOC-01, issue #1109).

Lives alongside ``adapters/local_backend/``; each ``adapters/``
subpackage owns one transport. The CP-1 filesystem adapter loads
contract template bodies from ``app/modules/contratos/templates/``;
no SQL, no FastAPI, no S3 imports allowed here.
"""
from __future__ import annotations

__all__: list[str] = []
