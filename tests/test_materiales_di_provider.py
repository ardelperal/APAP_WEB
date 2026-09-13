"""Behavioural tests for the materiales DI provider (issue #752, PR 4 of 5).

Verifies that :func:`app.modules.materiales.di.get_materiales_port`
returns a :class:`MaterialesPort` whose ten documented methods are
the concrete :class:`LocalBackendMaterialesAdapter` methods. The
test installs a fake ``request.app.state.sql_executor`` (a stub
``SqlExecutor``) so the provider can be exercised without spinning
up Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter import (
    LocalBackendMaterialesAdapter,
)
from app.modules.materiales.di import get_materiales_port


class _StubExecutor:
    """Minimal SqlExecutor stand-in.

    ``execute_sql`` records every call so the test can assert the
    adapter was the one constructed (the ``get_material_by_id``
    call below should produce exactly one ``execute_sql`` invocation,
    not two or zero).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list | None]] = []

    def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
        self.calls.append((query, params))
        return []


def _request_with_executor(executor: _StubExecutor) -> SimpleNamespace:
    """Build a request-like object whose ``app.state.sql_executor`` is the stub."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(sql_executor=executor)))


def test_get_materiales_port_returns_a_materiales_port() -> None:
    """The provider yields the LocalBackend adapter that satisfies the Protocol.

    The project's :class:`MaterialesPort` is a ``Protocol`` without
    ``@runtime_checkable`` — duck-typing is the idiom (mirrors the
    pin in ``test_materiales_adapter_architecture.py``). The
    isinstance check goes through ``LocalBackendMaterialesAdapter``
    directly; Protocol membership is asserted by the eight-method
    pin in ``test_slice_materiales_architecture.py``.
    """
    stub = _StubExecutor()
    request = _request_with_executor(stub)

    gen = get_materiales_port(request)
    port = next(gen)
    try:
        assert isinstance(port, LocalBackendMaterialesAdapter)
        # The duck-typed Protocol check: every documented port
        # method exists on the returned adapter.
        for name in (
            "create_material",
            "get_material_by_id",
            "list_materials",
            "update_material",
            "deactivate_material",
            "assign_material_to_estancia",
            "list_materials_for_estancia",
            "remove_material_from_estancia",
            "estancia_is_open_and_active",
            "material_is_active",
        ):
            assert callable(getattr(port, name, None)), (
                f"adapter must expose {name} (Protocol duck-typing)"
            )
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def test_get_materiales_port_uses_the_request_scoped_executor() -> None:
    """The provider wraps the lifespan-cached ``app.state.sql_executor``.

    No fallback to a fresh ``LocalPostgresExecutor`` when the state
    attribute is present — that branch is the helper's job, but the
    provider itself must not re-implement it.
    """
    stub = _StubExecutor()
    request = _request_with_executor(stub)

    gen = get_materiales_port(request)
    port = next(gen)
    try:
        port.get_material_by_id("00000000-0000-0000-0000-000000000001")
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    assert len(stub.calls) == 1, (
        "the adapter built by get_materiales_port must call the "
        "lifespan-supplied executor exactly once per port method call"
    )
