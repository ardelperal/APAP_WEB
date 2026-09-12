"""Architectural pin test for the materiales slice (issue #752, PR 1 of 5).

Per AGENTS.md §33.4: "Cada slice envía un test pin arquitectónico que
falla cuando un import de transporte se filtra a la capa equivocada.
Una regla sin gate es [anti-patterns.md] §32.P3."

This file pins the architectural invariants of the materiales
hexagonal slice:

1. ``app/modules/materiales/domain/`` is transport-free — no
   ``SqlExecutor``, no ``psycopg``, no ``app.core.local_backend``
   imports.
2. ``app/modules/materiales/ports/`` is transport-free — same rule.
   The port is an abstract surface (Protocol); the concrete adapter
   is in ``adapters/local_backend/`` (PR 2 of #752) and is the only
   layer allowed to import transport.

A regression that adds ``from app.core.data_access import SqlExecutor``
to ``ports/materiales_port.py`` fails this gate immediately.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no fixtures; the test parses the source tree
  directly with ``pathlib`` + ``re``. Fast, hermetic, no I/O.
- Rule 4 (no humo): the assertions name the specific disallowed
  imports; the failure message lists every violation found.
- Rule 8 (no production mutation): the test reads files only.
"""

from __future__ import annotations

import re
from pathlib import Path

# Module-level pins for layer boundaries. Each entry is the exact
# substring searched in every source file under the corresponding
# directory; if any file contains it the test fails.
#
# Reasoning per substring:
# - "app.core.data_access" : brings ``SqlExecutor`` / ``BackendError``.
#   Domain and ports depend on Protocol abstractions, not on the data
#   access layer (AGENTS.md §31).
# - "app.core.local_backend" : the only layer allowed to talk to the
#   concrete LocalBackend executor is ``adapters/local_backend/``
#   (PR 2 of #752). Domain and ports must stay transport-free.
# - "psycopg" : psycopg2/psycopg3 is the driver for the executor. Same
#   rule: never in domain/ports.
DISALLOWED_IN_DOMAIN_AND_PORTS = frozenset(
    {
        "app.core.data_access",
        "app.core.local_backend",
        "psycopg",
    }
)

MATERIALES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "materiales"

LAYERS_THAT_MUST_BE_TRANSPORT_FREE = ("domain", "ports")


def _python_files_in(layer: str) -> list[Path]:
    """Return every Python file under ``app/modules/materiales/<layer>/``.

    Excludes ``__pycache__`` (compiled artifacts, not source).
    """
    layer_root = MATERIALES_ROOT / layer
    if not layer_root.exists():
        return []
    return [
        path
        for path in layer_root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _extract_imports(source: str) -> list[str]:
    """Return every module path referenced by an ``import`` or
    ``from ... import ...`` statement in ``source``.

    Handles the multiline form ``from module import (\n  a,\n  b,\n)``
    that some adapters use.
    """
    pattern = re.compile(
        r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))",
        re.MULTILINE,
    )
    found: list[str] = []
    for match in pattern.finditer(source):
        module = match.group(1) or match.group(2)
        if module:
            found.append(module)
    return found


def test_domain_layer_is_transport_free() -> None:
    """Every file in ``domain/`` stays free of transport imports.

    A regression that lets ``psycopg`` or ``SqlExecutor`` leak into
    the domain breaks rule §31 (domain depends on Protocol abstractions)
    and §33.4 (the pin must exist for every slice). Failure lists the
    offending file + import so a human can fix the regression in one
    place.
    """
    violations: list[str] = []
    for path in _python_files_in("domain"):
        source = path.read_text(encoding="utf-8")
        for module in _extract_imports(source):
            for disallowed in DISALLOWED_IN_DOMAIN_AND_PORTS:
                if module == disallowed or module.startswith(
                    disallowed + "."
                ):
                    violations.append(f"{path.relative_to(MATERIALES_ROOT)}: {module}")
    assert not violations, (
        "domain/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_ports_layer_is_transport_free() -> None:
    """Every file in ``ports/`` stays free of transport imports.

    Mirrors ``test_domain_layer_is_transport_free`` for the port
    layer. The port is a ``Protocol``; its concrete implementation
    belongs under ``adapters/local_backend/`` (PR 2 of #752). A leak
    would couple the abstract surface to LocalBackend and break every
    future adapter (e.g. an HTTP-backed test fake).
    """
    violations: list[str] = []
    for path in _python_files_in("ports"):
        source = path.read_text(encoding="utf-8")
        for module in _extract_imports(source):
            for disallowed in DISALLOWED_IN_DOMAIN_AND_PORTS:
                if module == disallowed or module.startswith(
                    disallowed + "."
                ):
                    violations.append(f"{path.relative_to(MATERIALES_ROOT)}: {module}")
    assert not violations, (
        "ports/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_port_exposes_eight_use_case_methods_plus_two_probes() -> None:
    """The Protocol declares the eight use cases + two FK probes.

    The eight methods mirror the legacy public surface of
    ``service.py`` (five catalog CRUD) plus
    ``estancia_material_service.py`` (three junction CRUD). PR 3
    adds two FK-probe methods (``estancia_is_open_and_active`` and
    ``material_is_active``) so the application-layer assign use
    case can enforce the same policy the legacy validators did
    without importing SQL into ``application/``. Adding a method
    to the port without updating this list (or removing one
    without also updating the legacy service) is a real
    regression; the test pins the parity until PR 5 deletes the
    legacy service module.
    """
    expected = {
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
    }
    port_path = MATERIALES_ROOT / "ports" / "materiales_port.py"
    source = port_path.read_text(encoding="utf-8")
    declared: set[str] = set()
    for match in re.finditer(r"^\s*def\s+(\w+)\s*\(", source, re.MULTILINE):
        declared.add(match.group(1))
    missing = expected - declared
    extra = declared - expected
    assert not missing and not extra, (
        f"MaterialesPort must declare exactly {sorted(expected)}; "
        f"missing={sorted(missing)}, extra={sorted(extra)}"
    )


def test_domain_does_not_re_export_via_legacy_service() -> None:
    """``service.py`` re-imports the dataclasses from ``domain/``.

    PR 1 moves the definitions out of ``service.py``; the legacy
    module re-imports them under the legacy path so existing callers
    (routes, use cases, tests) keep working unchanged until PR 5
    deletes ``service.py``. If the move is reverted accidentally
    (someone re-defines the dataclasses inside ``service.py``) the
    test fails because the ``def class Material`` body is missing
    from the legacy module — the import would become a no-op rename.
    """
    service_path = MATERIALES_ROOT / "service.py"
    source = service_path.read_text(encoding="utf-8")
    # The legacy module must IMPORT the dataclass, not DEFINE it.
    assert "class Material(" not in source, (
        "service.py must not redefine Material; the dataclass lives in "
        "app/modules/materiales/domain/material.py and is re-imported here."
    )
    assert "class EstanciaMaterial(" not in source, (
        "service.py must not redefine EstanciaMaterial; the dataclass lives in "
        "app/modules/materiales/domain/estancia_material.py and is re-imported here."
    )
    assert "class MaterialConflictError(" not in source, (
        "service.py must not redefine MaterialConflictError; the exception lives in "
        "app/modules/materiales/domain/exceptions.py and is re-imported here."
    )
    assert (
        "from app.modules.materiales.domain.material import Material" in source
    ), "service.py must re-import Material from the domain layer"
    assert (
        "from app.modules.materiales.domain.estancia_material import EstanciaMaterial"
        in source
    ), "service.py must re-import EstanciaMaterial from the domain layer"
    assert (
        "from app.modules.materiales.domain.exceptions import MaterialConflictError"
        in source
    ), "service.py must re-import MaterialConflictError from the domain layer"
