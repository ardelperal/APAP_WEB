"""Hexagonal port for the schema-bootstrap surface.

The application layer depends on this :class:`Protocol`; the InsForge
adapter implements it. Tests can implement it with an in-memory fake
without spinning up transport or HTTP.

The port carries two operations:

1. ``ensure_domain_schema`` — bootstrap every domain table that the
   ``app.core.domain_*`` submodules declare (the 23-statement DDL
   sequence originally called by :func:`app.core.domain.ensure_domain_schema`).
2. ``run_idempotent_sql`` — the replay-safe SQL executor used by the
   bootstrap itself and by every other cold-start path
   (``ensure_catalogs``, ``ensure_schema_and_seed``). Idempotence stays
   a property of each supplied statement (``CREATE TABLE IF NOT
   EXISTS``, ``ON CONFLICT DO NOTHING``, etc.); the port only owns the
   ordered execution plus failure telemetry.

Hexagonal taxonomy:

- **Port**    (this module)                              — abstract surface.
- **Application** (:mod:`app.core.application.schema_bootstrap`) — use cases.
- **Adapter** (:mod:`app.core.adapters.insforge.schema_bootstrap_insforge_adapter`) — InsForge impl.
- **DI**      (:mod:`app.core.di.schema_bootstrap_di`)    — wiring.

Rule §31 (domain services depend on Protocol abstractions): every
method here takes a port reference, never a concrete backend client.
Rule §22 (SQL/service separation): the SQL strings live in the adapter,
not in the port or the application layer.
"""


from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SqlStatement:
    """One bootstrap SQL statement and its optional positional parameters.

    Replay-safe DDL/DML is expressed as a sequence of these; the port
    walks them in order and stops on the first failure, propagating the
    underlying exception after emitting one
    ``schema_bootstrap.failed`` log event.

    Attributes:
        query: The raw SQL string (typically a ``CREATE TABLE IF NOT
            EXISTS``, an ``INSERT ... ON CONFLICT DO NOTHING``, or a
            migration ``ALTER TABLE``).
        params: Optional positional parameter list. ``None`` is treated
            the same as an empty list.
    """

    query: str
    params: list[Any] | None = None


class SchemaBootstrapPort(Protocol):
    """Abstract surface for schema-bootstrap operations.

    Implementations:

    - :class:`app.core.adapters.insforge.schema_bootstrap_insforge_adapter.InsForgeSchemaBootstrapAdapter`
      — production adapter, talks to InsForge via :class:`SqlExecutor`.
    - Test fakes (in ``tests/``) — in-memory adapters that record calls
      or raise on demand without any transport.
    """

    def ensure_domain_schema(self) -> None:
        """Bootstrap every domain table in the canonical dependency order.

        Order respects FK dependencies between the ``app.core.domain_*``
        submodules (roots first, junction tables last) — see the
        adapter for the exact 28-statement sequence.
        """
        ...

    def run_idempotent_sql(
        self,
        statements: Sequence[SqlStatement],
        *,
        step_name: str,
    ) -> None:
        """Execute replay-safe statements in order and fail fast on errors.

        Idempotence remains a property of each supplied SQL statement
        (for example ``IF NOT EXISTS`` or ``ON CONFLICT DO NOTHING``).
        The port centralizes ordered execution and safe failure
        telemetry without swallowing or translating the original
        database exception.

        Args:
            statements: The statements to execute, in order.
            step_name: A short label (``"domain"``, ``"catalogs"``,
                ``"auth"``) attached to the failure log so the operator
                can pinpoint which bootstrap step blew up.
        """
        ...


__all__ = ["SchemaBootstrapPort", "SqlStatement"]
