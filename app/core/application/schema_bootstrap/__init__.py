"""Use-case layer for the schema-bootstrap slice.

Each function in this package is a thin orchestrator that delegates to
the :class:`SchemaBootstrapPort` interface. The use cases do NOT do
validation, query construction, or I/O — those concerns live in the
adapter (:mod:`app.core.adapters.insforge.schema_bootstrap_insforge_adapter`).
The single-line delegation is deliberate: it makes the orchestrator
trivially testable (a single ``port.<method>()`` call, mocked at the
port boundary) and keeps the seam between "what the app wants to do"
and "how the backend serves it" explicit.

Hexagonal taxonomy:

- Port      :mod:`app.core.ports.schema_bootstrap_port` (Protocol)
- THIS      :mod:`app.core.application.schema_bootstrap` (use cases)
- Adapter   :mod:`app.core.adapters.insforge.schema_bootstrap_insforge_adapter`
- DI        :mod:`app.core.di.schema_bootstrap_di`
"""


from __future__ import annotations

from app.core.application.schema_bootstrap.ensure_domain_schema import (
    ensure_domain_schema,
)
from app.core.application.schema_bootstrap.run_idempotent_sql import (
    run_idempotent_sql,
)

__all__ = ["ensure_domain_schema", "run_idempotent_sql"]
