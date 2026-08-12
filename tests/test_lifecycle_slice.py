"""Architectural pin tests for the lifecycle slice (LIFECYCLE-03, PR-A).

Fails today (no slice yet) and is the contract for the
slice-completeness gate per AGENTS.md §33.4. PR-A only ships pins #1
and #2; the remaining pins land with PR-B / PR-C.
"""

from __future__ import annotations

import ast
import pathlib

import pytest


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
    from app.modules.lifecycle.domain.animal_state import (
        DerivationKind,
        DerivationResult,
    )
    from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort

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
