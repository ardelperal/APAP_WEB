"""Stub adapter for ``SchemaBootstrapPort`` — pending local-backend implementation.

This file replaces the deleted :class:`app.core.adapters.local_backend.schema_bootstrap_local_backend_adapter.LocalBackendSchemaBootstrapAdapter`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud.

Affected operations (raise until the real adapter lands):

- :func:`app.core.domain.ensure_domain_schema` (delegated to
  :meth:`SchemaBootstrapPort.ensure_domain_schema`).

See issue #4b' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort


class StubSchemaBootstrapPort(SchemaBootstrapPort):
    """Placeholder :class:`SchemaBootstrapPort` whose every method raises."""

    def run_idempotent_sql(self, *args, **kwargs):
        raise NotImplementedError(
            "SchemaBootstrapPort.run_idempotent_sql: pending local-backend adapter, see #4b'"
        )

    def ensure_domain_schema(self, *args, **kwargs):
        raise NotImplementedError(
            "SchemaBootstrapPort.ensure_domain_schema: pending local-backend adapter, see #4b'"
        )


__all__ = ["StubSchemaBootstrapPort"]
