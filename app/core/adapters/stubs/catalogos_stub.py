"""Stub adapter for ``CatalogosPort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.core.adapters.stubs.catalogos_stub.legacy_LocalBackendCatalogosAdapter`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected routes (return 500 until the real adapter lands):

- ``GET /api/origenes`` + ``GET /api/motivos`` + ``GET /api/pruebas`` + ``GET /api/periodicidad`` + ``GET /api/especies`` + ``GET /api/tipos_contrato`` (delegated to :meth:`CatalogosPort.list_*`).

Note: :func:`app.core.catalogs.ensure_catalogs` runs at lifespan and
also delegates to ``CatalogosPort``. Until this stub is replaced with a
real adapter, the catalog bootstrap will fail at startup unless the
seed data is loaded through another path (e.g. SQL migration).

See issue #4b' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.core.ports.catalogos_port import CatalogosPort


class StubCatalogosPort(CatalogosPort):
    """Placeholder :class:`CatalogosPort` whose every method raises."""

    def list_origenes(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_origenes: pending local-backend adapter, see #4b'"
        )

    def list_motivos(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_motivos: pending local-backend adapter, see #4b'"
        )

    def list_pruebas(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_pruebas: pending local-backend adapter, see #4b'"
        )

    def list_periodicidad(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_periodicidad: pending local-backend adapter, see #4b'"
        )

    def list_tipos_contrato(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_tipos_contrato: pending local-backend adapter, see #4b'"
        )

    def list_especies(self, *args, **kwargs):
        raise NotImplementedError(
            "CatalogosPort.list_especies: pending local-backend adapter, see #4b'"
        )


__all__ = ["CatalogosPort"]
