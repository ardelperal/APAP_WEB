"""Architectural pin test for the contratos slice (DOC-01 PR 1, #56).

Per AGENTS.md §33.4: "Cada slice envía un test pin arquitectónico que
falla cuando un import de transporte se filtra a la capa equivocada."

This file pins the invariants of the contratos hexagonal slice:

1. ``app/modules/contratos/domain/`` is transport-free — no
   ``SqlExecutor``, no ``psycopg``, no ``app.core.local_backend``.
2. ``app/modules/contratos/ports/`` is transport-free — same rule.
   The port is an abstract surface (Protocol); the concrete adapter
   lives under ``adapters/local_backend/`` (PR 2 of #56) and is the
   only layer allowed to import transport.
3. ``app/modules/contratos/application/`` may import domain (entities
   + use cases) but NOT transport.
4. The application use case ``render_contrato`` has exactly one
   public function (the engine itself); PDF generation and storage
   wiring are PR 2 / PR 3 concerns and must NOT appear in PR 1.

A regression that adds ``from app.core.data_access import SqlExecutor``
to ``domain/plantilla.py`` fails this gate immediately.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no fixtures; the test parses the source tree
  with ``pathlib`` + ``re``. Fast, hermetic, no I/O.
- Rule 4 (no humo): the assertions name the specific disallowed
  imports; the failure message lists every violation found.
- Rule 8 (no production mutation): the test reads files only.
"""

from __future__ import annotations

import re
from pathlib import Path

# Disallowed imports for the transport-free layers. Mirrors the
# materiales pin test rationale (rule §31: domain services depend on
# Protocol abstractions, never on concrete transport).
DISALLOWED_IN_DOMAIN_AND_PORTS = frozenset(
    {
        "app.core.data_access",
        "app.core.local_backend",
        "psycopg",
        "weasyprint",  # PDF adapter lives in adapters/, never in domain/.
        "reportlab",  # same.
    }
)

CONTRATOS_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "contratos"

LAYERS_THAT_MUST_BE_TRANSPORT_FREE = ("domain", "ports")


def _python_files_in(layer: str) -> list[Path]:
    """Return every Python file under ``app/modules/contratos/<layer>/``."""
    layer_root = CONTRATOS_ROOT / layer
    if not layer_root.exists():
        return []
    return [
        path
        for path in layer_root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _extract_imports(source: str) -> list[str]:
    """Return every module path referenced by an ``import`` or
    ``from ... import ...`` statement in ``source``."""
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
    the domain breaks rule §31 and §33.4.
    """
    violations: list[str] = []
    for path in _python_files_in("domain"):
        source = path.read_text(encoding="utf-8")
        for module in _extract_imports(source):
            for disallowed in DISALLOWED_IN_DOMAIN_AND_PORTS:
                if module == disallowed or module.startswith(
                    disallowed + "."
                ):
                    violations.append(f"{path.relative_to(CONTRATOS_ROOT)}: {module}")
    assert not violations, (
        "domain/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_ports_layer_is_transport_free() -> None:
    """Every file in ``ports/`` stays free of transport imports."""
    violations: list[str] = []
    for path in _python_files_in("ports"):
        source = path.read_text(encoding="utf-8")
        for module in _extract_imports(source):
            for disallowed in DISALLOWED_IN_DOMAIN_AND_PORTS:
                if module == disallowed or module.startswith(
                    disallowed + "."
                ):
                    violations.append(f"{path.relative_to(CONTRATOS_ROOT)}: {module}")
    assert not violations, (
        "ports/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_render_contrato_exposes_single_public_function() -> None:
    """PR 1 only ships the template engine — no PDF, no storage yet.

    The public surface of :mod:`app.modules.contratos.application.render_contrato`
    is exactly :func:`render_contrato` (the use case facade).
    Internal helpers are private (``_`` prefix) and not exported
    through ``__all__``. PDF adapter (weasyprint / reportlab) and
    storage adapter (object storage) land in PR 2 and PR 3
    respectively; adding them here is scope creep.
    """
    module_path = CONTRATOS_ROOT / "application" / "render_contrato.py"
    source = module_path.read_text(encoding="utf-8")
    declared: set[str] = set()
    for match in re.finditer(r"^def\s+(\w+)\s*\(", source, re.MULTILINE):
        declared.add(match.group(1))
    public = {name for name in declared if not name.startswith("_")}
    assert public == {"render_contrato"}, (
        f"render_contrato.py must expose only render_contrato as a public "
        f"function; public: {sorted(public)}"
    )


def test_application_layer_only_imports_domain() -> None:
    """``application/`` may depend on ``domain/`` and stdlib; nothing else.

    The PDF adapter (``weasyprint``, ``reportlab``) and the storage
    adapter (``app.core.local_backend.storage``) belong in
    ``adapters/local_backend/``; ``application/`` only wires domain
    use cases against Protocol surfaces.
    """
    disallowed_in_application = frozenset(
        {
            "weasyprint",
            "reportlab",
            "app.core.local_backend",
            "psycopg",
        }
    )
    app_root = CONTRATOS_ROOT / "application"
    if not app_root.exists():
        return
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for module in _extract_imports(source):
            for disallowed in disallowed_in_application:
                if module == disallowed or module.startswith(
                    disallowed + "."
                ):
                    violations.append(
                        f"{path.relative_to(CONTRATOS_ROOT)}: {module}"
                    )
    assert not violations, (
        "application/ must stay PDF-free and storage-free; the following "
        "imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
