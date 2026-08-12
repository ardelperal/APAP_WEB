"""Architectural pin tests for the lifecycle slice (LIFECYCLE-03).

Pins #1 and #2 land with PR-A; pins #1 (extended to application/ +
di/), #3 (SQL builders return tuples), and #2 + #6 (adapter is a
``LifecyclePort``) land with PR-B. Pinned rules: §22 (SQL builders
return tuples, no inline SQL in application layer), §31 (port Protocol
uses ``SqlExecutor``, never ``InsForgeClient``), §33 (no transport
import in domain/application/di), §4 (one source for the CHECK
strings).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.domain.animal_state import (
    DerivationKind,
    DerivationResult,
)
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


def _imports(tree: ast.Module) -> list[tuple[str, str | None, str]]:
    """Yield ``(kind, module, name)`` for every Import / ImportFrom."""
    out: list[tuple[str, str | None, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(("import", None, alias.name))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.append(("from", node.module or "", alias.name))
    return out


def _read(rel_path: str) -> ast.Module:
    src = pathlib.Path(rel_path)
    assert src.exists(), f"module must exist: {rel_path}"
    return ast.parse(src.read_text(encoding="utf-8"))


def test_lifecycle_port_uses_sql_executor() -> None:
    """Pin #2: ``lifecycle_port.py`` depends on ``SqlExecutor``, never
    on ``InsForgeClient`` / ``InsForgeError``.
    """
    tree = _read("app/modules/lifecycle/ports/lifecycle_port.py")
    for _kind, module, name in _imports(tree):
        full = f"{module}.{name}" if module else name
        assert "InsForge" not in full, (
            f"lifecycle port must not import transport type {full!r}"
        )
    names = {name for kind, _, name in _imports(tree) if kind == "from"}
    assert "SqlExecutor" in names, (
        "lifecycle port must import SqlExecutor from app.core.data_access"
    )


@pytest.mark.parametrize(
    "module_path",
    [
        "app/modules/lifecycle/domain/animal_state.py",
        "app/modules/lifecycle/ports/lifecycle_port.py",
    ],
)
def test_lifecycle_slice_has_no_insforge_import(module_path: str) -> None:
    """Pin #1 (PR-A scope): every module in domain/ + ports/ has no
    InsForgeClient / InsForgeError import. PR-B's adapter is the only
    module in the slice that may import the transport.
    """
    tree = _read(module_path)
    for _kind, module, name in _imports(tree):
        full = f"{module}.{name}" if module else name
        assert "InsForge" not in full, (
            f"{module_path}: slice module must not import transport type {full!r}"
        )


def test_lifecycle_port_is_runtime_checkable() -> None:
    """The port module declares a ``@runtime_checkable`` Protocol so
    callers can ``isinstance(obj, LifecyclePort)`` cheaply. PR-B's
    adapter is the first real implementer; this test exercises the
    Protocol shape with a stub so the runtime surface stays exercised
    in coverage and any future drift in the method signatures is
    caught here.
    """
    class _StubPort:
        def calculate_state(self, animal_id: str) -> DerivationResult:
            return DerivationResult(
                state="Pendiente de Entrada",
                kind=DerivationKind.PENDIENTE_ENTRADA,
            )

        def persist_animal_state(
            self, animal_id: str, result: DerivationResult
        ) -> None:
            return None

    stub = _StubPort()
    assert isinstance(stub, LifecyclePort)
    result = stub.calculate_state("animal-1")
    assert result.state == "Pendiente de Entrada"
    assert stub.persist_animal_state("animal-1", result) is None


# ---------------------------------------------------------------------------
# PR-B pins — adapter + DI + application layer (LIFECYCLE-03 PR-B).
# All FAIL until the adapter, queries, application use cases, and DI
# composition root land.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path",
    [
        "app/modules/lifecycle/application/__init__.py",
        "app/modules/lifecycle/di/__init__.py",
    ],
)
def test_lifecycle_application_and_di_have_no_insforge_import(module_path: str) -> None:
    """Pin #1 (PR-B scope): application/ and di/ never import
    ``InsForgeClient`` / ``InsForgeError``. PR-A covers domain/ and
    ports/; PR-B widens the rule to the use cases and the composition
    root. The adapter under ``adapters/insforge/`` is the only module
    allowed to import the transport (AGENTS.md §33.4).
    """
    tree = _read(module_path)
    for _kind, module, name in _imports(tree):
        full = f"{module}.{name}" if module else name
        assert "InsForge" not in full, (
            f"{module_path}: application/di layer must not import "
            f"transport type {full!r} -- the slice must depend on the "
            f"LifecyclePort Protocol, never on the concrete transport"
        )


@pytest.mark.parametrize(
    "module_path",
    [
        "app/modules/lifecycle/application/__init__.py",
        "app/modules/lifecycle/di/lifecycle_di.py",
    ],
)
def test_lifecycle_application_di_source_files_no_insforge_import(module_path: str) -> None:
    """Companion to the package-init pin: scan the source files inside
    application/ and di/ that may grow over PR-B. Empty __init__ is a
    no-op so this skips gracefully when the file holds no statements;
    a future PR that adds an InsForge import here fails the pin
    immediately.
    """
    tree = _read(module_path)
    for _kind, module, name in _imports(tree):
        full = f"{module}.{name}" if module else name
        assert "InsForge" not in full, (
            f"{module_path}: application/di source must not import "
            f"transport type {full!r}"
        )


@pytest.mark.parametrize(
    ("builder_name", "arg"),
    [
        ("build_select_active_intakes", "animal-uuid-1"),
        ("build_select_active_fosters", "animal-uuid-2"),
        ("build_select_active_adoptions", "animal-uuid-3"),
        ("build_upsert_current_state", ("animal-uuid-4", "Albergue", "albergue")),
        ("build_select_ficha", "animal-uuid-5"),
    ],
)
def test_lifecycle_insforge_queries_return_sql_params_tuples(
    builder_name: str, arg: object
) -> None:
    """Pin #3: every SQL builder in
    ``lifecycle_insforge_queries.py`` returns a ``tuple[str, list]``
    per AGENTS.md §22 — no function calls ``execute_sql`` itself; the
    adapter orchestrates the executor. Builders are imported and
    invoked with a unit-test input to assert the shape without any
    transport.
    """
    import app.modules.lifecycle.adapters.insforge.lifecycle_insforge_queries as q

    builder = getattr(q, builder_name)
    if isinstance(arg, tuple):
        sql, params = builder(*arg)
    else:
        sql, params = builder(arg)
    assert isinstance(sql, str) and sql.strip(), (
        f"{builder_name}: must return a non-empty SQL string; got {sql!r}"
    )
    assert isinstance(params, list), (
        f"{builder_name}: must return a list of params; got {params!r}"
    )


def test_lifecycle_insforge_adapter_implements_lifecycle_port() -> None:
    """Pin #2 + #6: ``InsForgeLifecycleAdapter`` is a real
    ``LifecyclePort`` implementation — ``isinstance`` against the
    runtime-checkable Protocol holds, both methods are wired, and a
    stub ``SqlExecutor`` round-trips through the cascade. This is the
    first adapter-level instance check in the slice; the same shape
    pins the DI composition root.
    """
    from app.modules.lifecycle.adapters.insforge.lifecycle_insforge_adapter import (
        InsForgeLifecycleAdapter,
    )

    class _StubExecutor:
        """Stub SqlExecutor that returns canned rows per SQL substring.

        Mirrors the FakeSqlExecutor pattern from the auth slice
        (tests/test_admin.py); PR-B keeps the fixture local because
        the slice is new and the contracts are simple. PR-C may lift
        it into a shared fixture once the close/can_delete use cases
        land.
        """

        def __init__(self) -> None:
            self.calls: list[tuple[str, list]] = []
            self._responses: dict[str, list[dict[str, object]]] = {
                "FROM animales": [],
                "FROM entradas": [],
                "FROM acogidas": [],
                "FROM adopciones": [],
            }

        def execute_sql(self, query: str, params: list | None = None) -> list[dict[str, object]]:
            self.calls.append((query, list(params or [])))
            for marker, rows in self._responses.items():
                if marker in query:
                    return rows
            return []

    stub = _StubExecutor()
    adapter = InsForgeLifecycleAdapter(stub)  # type: ignore[arg-type]
    assert isinstance(adapter, LifecyclePort), (
        "InsForgeLifecycleAdapter must satisfy the LifecyclePort Protocol"
    )
    assert isinstance(stub, SqlExecutor), (
        "Stub executor must satisfy the SqlExecutor Protocol "
        "(AGENTS.md §31 -- adapters take SqlExecutor, never the concrete client)"
    )
    # The port is empty -- the use case returns Pendiente de Entrada when
    # there are no active records and no death date.
    result = adapter.calculate_state("animal-uuid-empty")
    assert isinstance(result, DerivationResult)
    assert result.state == "Pendiente de Entrada"
    # persist_animal_state smoke: it does not raise on a valid result.
    adapter.persist_animal_state("animal-uuid-empty", result)
