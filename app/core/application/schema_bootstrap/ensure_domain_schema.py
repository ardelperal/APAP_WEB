"""Use case: bootstrap every domain table in dependency order.

Thin orchestrator over :class:`SchemaBootstrapPort`. Hexagonal contract:

- Inputs: the port (depends on :class:`SchemaBootstrapPort` Protocol,
  not on any concrete backend).
- Outputs: none — the side effect (DDL emitted against the backend) is
  owned by the adapter.
- Side effects: schema mutations on whichever backend the adapter
  talks to. In production that is LocalBackend; in tests it is whatever
  fake implements the port.

The split between the use case and the adapter is deliberate: the
adapter is the seam where the 28-statement DDL sequence lives (rule
§22 — query construction is its own seam), and the use case only
states *what* the application wants to do. Tests can verify the
orchestration contract by passing an in-memory port that records the
call, without ever materialising a single SQL string.
"""


from __future__ import annotations

from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort


def ensure_domain_schema(port: SchemaBootstrapPort) -> None:
    """Idempotently create all domain tables via the bootstrap port.

    The dependency order — roots (``animales``, ``voluntarios``) first,
    junction tables (``materiales`` / ``estancia_materiales``) last —
    lives in the adapter. This use case only delegates.

    Args:
        port: The schema-bootstrap port implementation injected by the
            DI layer (``app/core/di/schema_bootstrap_di.py``) or
            constructed ad-hoc in tests.
    """
    port.ensure_domain_schema()


__all__ = ["ensure_domain_schema"]
