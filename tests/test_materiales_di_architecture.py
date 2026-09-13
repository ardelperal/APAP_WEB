"""Architectural pin tests for the materiales DI layer (issue #752, PR 4 of 5).

The DI layer is the composition root for the materiales bounded
context: it owns the request-scoped :class:`MaterialesPort` lifetime
and hides the concrete :class:`LocalBackendMaterialesAdapter` from
the route and application layers.

Pins PR 4 enforces:

1. The ``di/`` module exposes a single public
   ``get_materiales_port`` dependency provider that returns the
   :class:`MaterialesPort` Protocol — never the concrete adapter.
2. The DI provider does not import :class:`SqlExecutor`,
   :class:`LocalPostgresExecutor`, or anything from
   ``app.core.local_backend`` directly; it composes them via the
   shared ``yield_local_backend_port`` helper so the lifespan /
   fallback logic lives in one place.
3. The ``di/`` module is not imported by ``domain/``, ``ports/``,
   ``adapters/``, or ``application/`` — defense in depth.
"""

from __future__ import annotations

import ast
from pathlib import Path

MATERIALES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "materiales"
DI_DIR = MATERIALES_ROOT / "di"


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
    """Return AST-level violations when ``source`` imports ``module_name``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name or alias.name.startswith(module_name + "."):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module_name or node.module.startswith(module_name + "."):
                violations.append(f"from {node.module} import ...")
    return violations


def test_di_exposes_get_materiales_port() -> None:
    """``di/__init__.py`` re-exports the provider.

    The route layer imports ``from app.modules.materiales.di import
    get_materiales_port`` (mirrors ``from app.modules.animals.di
    import get_animals_port``). If the symbol is missing or renamed
    the import fails and the routes can't be wired to the port.
    """
    init_path = DI_DIR / "__init__.py"
    assert init_path.exists(), "app/modules/materiales/di/__init__.py missing"
    source = init_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
    assert "get_materiales_port" in names, (
        f"di/__init__.py must re-export get_materiales_port; got {sorted(names)}"
    )


def test_di_uses_shared_yield_local_backend_port_helper() -> None:
    """The DI provider delegates executor lookup to the shared helper.

    Re-implementing the lifespan / fallback dance inline duplicates
    :func:`app.core.di._yield_local_backend_port.yield_local_backend_port`
    (the same logic lives in ``catalogos_di``, ``oauth_di``,
    ``schema_bootstrap_di``). Pin: the provider MUST call the helper,
    not construct ``LocalPostgresExecutor`` directly.
    """
    provider_files = [
        p for p in _collect_python_sources(DI_DIR)
        if p.name != "__init__.py"
    ]
    assert provider_files, "no provider file found under di/"
    for path in provider_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        helper_used = False
        local_postgres_used = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "app.core.di._yield_local_backend_port":
                    helper_used = True
                if node.module == "app.core.local_backend.db":
                    local_postgres_used = True
        assert helper_used, (
            f"{path.relative_to(MATERIALES_ROOT)} must import "
            "yield_local_backend_port; otherwise the lifespan / "
            "fallback dance is duplicated"
        )
        assert not local_postgres_used, (
            f"{path.relative_to(MATERIALES_ROOT)} must not import "
            "LocalPostgresExecutor directly; route the executor "
            "through the shared helper"
        )


def test_di_does_not_import_transport_directly() -> None:
    """The DI provider does not touch ``SqlExecutor`` or ``LocalPostgresExecutor``."""
    forbidden = (
        "app.core.data_access",
        "app.core.local_backend",
    )
    violations: list[str] = []
    for path in _collect_python_sources(DI_DIR):
        source = path.read_text(encoding="utf-8")
        for module_name in forbidden:
            for stmt in _imports_source_contains(source, module_name):
                violations.append(
                    f"{path.relative_to(MATERIALES_ROOT)}: {stmt}"
                )
    assert not violations, (
        "di/ must compose transport via the shared helper, "
        "not import it directly:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_inward_layers_do_not_import_di() -> None:
    """``domain/``, ``ports/``, ``adapters/``, ``application/`` stay inward.

    The DI is a composition root — its consumers are routes and tests,
    never the inward hexagonal tiers.
    """
    di_module_prefix = "app.modules.materiales.di"
    forbidden_parents = (
        MATERIALES_ROOT / "domain",
        MATERIALES_ROOT / "ports",
        MATERIALES_ROOT / "adapters",
        MATERIALES_ROOT / "application",
    )
    violations: list[str] = []
    for parent in forbidden_parents:
        for path in _collect_python_sources(parent):
            source = path.read_text(encoding="utf-8")
            for stmt in _imports_source_contains(source, di_module_prefix):
                violations.append(
                    f"{path.relative_to(MATERIALES_ROOT)}: {stmt}"
                )
    assert not violations, (
        "inward tiers must not import di/; the composition root is "
        "for the route layer:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
