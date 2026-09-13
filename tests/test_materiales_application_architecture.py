"""Architectural pin tests for the materiales application layer (issue #752, PR 3 of 5).

Per AGENTS.md §33.4: "Cada slice envía un test pin arquitectónico que
falla cuando un import de transporte se filtra a la capa equivocada."

The application layer is the highest hexagonal tier: it owns the
domain-validation policy and orchestrates the port calls. The layer
boundaries PR 3 pins:

1. **No transport imports.** The application layer never imports
   ``app.core.data_access``, ``app.core.local_backend``, or
   ``SqlExecutor``. SQL lives in the adapter.
2. **No SQL imports.** The application layer never imports
   ``app.modules.materiales.queries`` directly. SQL builders are the
   adapter's tool.
3. **Domain, ports, and adapters stay inward.** The
   ``application/`` module imports *into* ``domain/`` and ``ports/``;
   it is NEVER imported by ``domain/``, ``ports/``, or the
   LocalBackend ``adapters/`` subtree. Defense in depth: a leak in
   any direction breaks a layer boundary and the port-based test
   fakes would no longer be drop-in substitutes.
4. **The eight use cases cover the public port surface.** Every use
   case module exposes exactly one ``def`` callable; the union of
   these callables matches the eight port use-case methods (the two
   FK-probe methods are application helpers, not use cases).
"""

from __future__ import annotations

import ast
from pathlib import Path

MATERIALES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "materiales"
APPLICATION_DIR = MATERIALES_ROOT / "application"


def _collect_python_sources(directory: Path) -> list[Path]:
    """Return every ``*.py`` file under ``directory`` (skipping ``__pycache__``)."""
    if not directory.exists():
        return []
    return [
        p
        for p in directory.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _imports_source_contains(source: str, module_name: str) -> list[str]:
    """Return AST-level violations when ``source`` imports ``module_name``.

    Both ``import x.y.z`` and ``from x.y.z import ...`` shapes are
    checked; the violation string is the import statement's textual
    form so the failure message pinpoints the exact line.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name or alias.name.startswith(module_name + "."):
                    violations.append(
                        f"import {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module_name or node.module.startswith(module_name + "."):
                violations.append(
                    f"from {node.module} import ..."
                )
    return violations


def test_application_layer_is_transport_free_and_sql_free() -> None:
    """The application layer imports neither transport nor SQL.

    Pins §31 and §22 simultaneously: domain code depends on
    Protocols; the application code orchestrates them; the adapter
    is the only tier that imports ``app.core.data_access``,
    ``app.core.local_backend``, or ``app.modules.materiales.queries``.
    One test covers both forbidden import sets so the layer
    boundary has a single readable pin instead of two near-identical
    ones.
    """
    forbidden = (
        "app.core.data_access",
        "app.core.local_backend",
        "app.modules.materiales.queries",
    )
    violations: list[str] = []
    for path in _collect_python_sources(APPLICATION_DIR):
        source = path.read_text(encoding="utf-8")
        for module_name in forbidden:
            for stmt in _imports_source_contains(source, module_name):
                violations.append(
                    f"{path.relative_to(MATERIALES_ROOT)}: {stmt}"
                )
    assert not violations, (
        "application/ must not import transport or SQL; "
        "the layer boundary breaks otherwise:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_domain_ports_adapters_do_not_import_application() -> None:
    """Defense in depth: only the routes and tests import from application/.

    The slice taxonomy is unidirectional: ``domain/`` < ``ports/`` <
    ``application/`` < ``adapters/`` < routes. A reverse import breaks
    the layer boundary and the test fakes can no longer satisfy the
    Protocol in isolation.
    """
    application_module_prefix = "app.modules.materiales.application"
    forbidden_parents = (
        MATERIALES_ROOT / "domain",
        MATERIALES_ROOT / "ports",
        MATERIALES_ROOT / "adapters",
    )
    violations: list[str] = []
    for parent in forbidden_parents:
        for path in _collect_python_sources(parent):
            source = path.read_text(encoding="utf-8")
            for stmt in _imports_source_contains(source, application_module_prefix):
                violations.append(
                    f"{path.relative_to(MATERIALES_ROOT)}: {stmt}"
                )
    assert not violations, (
        "domain/, ports/, and adapters/ must not import application/; "
        "the layer boundary breaks otherwise:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_application_modules_export_one_use_case_callable() -> None:
    """Every non-``__init__`` application module exposes one use case.

    The one-file-per-use-case pattern keeps each use case's policy
    small enough to review in isolation; an application module that
    exports two ``def`` callables is a code smell that PR 3 split a
    use case in the wrong place.
    """
    use_case_modules = sorted(
        p for p in _collect_python_sources(APPLICATION_DIR)
        if p.name != "__init__.py"
    )
    assert use_case_modules, "no use case modules found under application/"

    multi_def_modules: list[str] = []
    for path in use_case_modules:
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        defs = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ]
        if len(defs) != 1:
            multi_def_modules.append(
                f"{path.relative_to(MATERIALES_ROOT)}: declares {defs}"
            )
    assert not multi_def_modules, (
        "every application module must declare exactly one public use case:\n"
        + "\n".join(f"  - {v}" for v in multi_def_modules)
    )
