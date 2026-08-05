"""Use case: replay-safe ordered SQL execution during bootstrap.

Thin orchestrator over :class:`SchemaBootstrapPort`. Hexagonal contract:

- Inputs: the port (depends on :class:`SchemaBootstrapPort` Protocol,
  not on any concrete backend) and the sequence of statements to run.
- Outputs: none — execution side effects are owned by the adapter.
- Side effects: one DDL/DML emission per statement, in order, against
  whichever backend the adapter talks to. The first failure is
  logged and propagated untouched.

The use case does NOT own the failure-telemetry contract — that lives
in the port implementation — because the same shape is needed by
``ensure_domain_schema``, ``ensure_catalogs``, and
``ensure_schema_and_seed``, and we want a single seam.
"""


from __future__ import annotations

from collections.abc import Sequence

from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort, SqlStatement


def run_idempotent_sql(
    port: SchemaBootstrapPort,
    statements: Sequence[SqlStatement],
    *,
    step_name: str,
) -> None:
    """Execute replay-safe statements in order via the bootstrap port.

    Args:
        port: The schema-bootstrap port implementation injected by the
            DI layer or constructed ad-hoc in tests.
        statements: The statements to execute, in declared order.
        step_name: A short label (``"domain"``, ``"catalogs"``,
            ``"auth"``) attached to the failure log so the operator
            can pinpoint which bootstrap step blew up.
    """
    port.run_idempotent_sql(statements, step_name=step_name)


__all__ = ["run_idempotent_sql"]
