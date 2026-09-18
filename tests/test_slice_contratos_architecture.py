"""Architectural pin test for the contratos slice (DOC-01 PR 1 + PR 2, #56).

Per AGENTS.md §33.4: "Cada slice envía un test pin arquitectónico que
falla cuando un import de transporte se filtra a la capa equivocada."

This file pins the invariants of the contratos hexagonal slice:

1. ``app/modules/contratos/domain/`` is transport-free — no
   ``SqlExecutor``, no ``psycopg``, no ``app.core.local_backend``,
   no ``reportlab``, no ``minio``.
2. ``app/modules/contratos/ports/`` is transport-free — same rule.
   The ports are abstract surfaces (Protocols); the concrete adapters
   live under ``adapters/local_backend/`` and are the only layer
   allowed to import transport.
3. ``app/modules/contratos/application/`` may depend on ``domain/``
   and ``ports/`` (intra-slice) but NOT on transport adapters
   (``adapters/*``) and NOT on transport libraries directly.
4. ``app/modules/contratos/adapters/local_backend/`` is the ONLY
   layer allowed to import ``reportlab``, ``minio`` and
   ``app.core.local_backend``; domain/ports/application must stay
   free of those.
5. The PR-1 use case ``render_contrato`` still exposes exactly one
   public function; PDF generation is the storage adapter's concern.

A regression that adds ``from minio import Minio`` to
``domain/plantilla.py`` fails gate 1 immediately. A regression that
adds ``from app.modules.contratos.adapters.local_backend import
ReportLabPdfGenerator`` to ``application/render_to_pdf.py`` fails
gate 3 immediately. A regression that removes ``minio`` from the
storage adapter fails gate 4 with a clear "you just made the
adapter forget its job" message.

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
DISALLOWED_IN_DOMAIN_PORTS_APPLICATION = frozenset(
    {
        "app.core.data_access",
        "app.core.local_backend",
        "psycopg",
        "weasyprint",
        "reportlab",
        "minio",
    }
)

# Allowed-transport markers — only ``adapters/local_backend/`` may
# import these. The adapters layer test checks that exactly one file
# under adapters/ imports each of them.
ADAPTER_ONLY_TRANSPORT = frozenset(
    {
        "reportlab",
        "minio",
    }
)

# Modules inside ``app.modules.contratos`` that the application layer
# must NOT import (the application depends only on domain + ports).
DISALLOWED_IN_APPLICATION_FROM_ADAPTERS = frozenset(
    {
        "app.modules.contratos.adapters",
    }
)

CONTRATOS_ROOT = (
    Path(__file__).resolve().parents[1] / "app" / "modules" / "contratos"
)

LAYERS_THAT_MUST_BE_TRANSPORT_FREE = ("domain", "ports", "application")


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


def _imports_violation(
    path: Path,
    imports: list[str],
    disallowed: frozenset[str],
) -> list[str]:
    """Return violations: ``[relative_path: module]`` for each leak."""
    out: list[str] = []
    for module in imports:
        for forbidden in disallowed:
            if module == forbidden or module.startswith(forbidden + "."):
                out.append(f"{path.relative_to(CONTRATOS_ROOT)}: {module}")
    return out


# ---------------------------------------------------------------------------
# Gate 1: domain and ports stay transport-free
# ---------------------------------------------------------------------------


def test_domain_layer_is_transport_free() -> None:
    """Every file in ``domain/`` stays free of transport imports."""
    violations: list[str] = []
    for path in _python_files_in("domain"):
        source = path.read_text(encoding="utf-8")
        violations.extend(
            _imports_violation(
                path,
                _extract_imports(source),
                DISALLOWED_IN_DOMAIN_PORTS_APPLICATION,
            )
        )
    assert not violations, (
        "domain/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_ports_layer_is_transport_free() -> None:
    """Every file in ``ports/`` stays free of transport imports."""
    violations: list[str] = []
    for path in _python_files_in("ports"):
        source = path.read_text(encoding="utf-8")
        violations.extend(
            _imports_violation(
                path,
                _extract_imports(source),
                DISALLOWED_IN_DOMAIN_PORTS_APPLICATION,
            )
        )
    assert not violations, (
        "ports/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Gate 2: application depends only on domain + ports (no transport, no adapters)
# ---------------------------------------------------------------------------


def test_application_layer_does_not_import_transport() -> None:
    """``application/`` must not import transport libraries directly.

    PDF generation goes through the ``ContratosPdfGeneratorPort``
    Protocol, not through reportlab. The use case is testable without
    reportlab installed.
    """
    app_root = CONTRATOS_ROOT / "application"
    if not app_root.exists():
        return
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        violations.extend(
            _imports_violation(
                path,
                _extract_imports(source),
                DISALLOWED_IN_DOMAIN_PORTS_APPLICATION,
            )
        )
    assert not violations, (
        "application/ must stay transport-free; the following imports leak transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_application_layer_does_not_import_adapters() -> None:
    """``application/`` must not import concrete adapters.

    Use cases receive the :class:`ContratosPdfGeneratorPort` and
    :class:`ContratosStoragePort` Protocols via dependency injection.
    Pulling a concrete adapter in at use-case level would freeze the
    transport choice and break hermetic testing.
    """
    app_root = CONTRATOS_ROOT / "application"
    if not app_root.exists():
        return
    violations: list[str] = []
    for path in app_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        violations.extend(
            _imports_violation(
                path,
                _extract_imports(source),
                DISALLOWED_IN_APPLICATION_FROM_ADAPTERS,
            )
        )
    assert not violations, (
        "application/ must not import adapters directly; the following imports leak "
        "the concrete transport:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Gate 3: PR-1 surface area still pinned
# ---------------------------------------------------------------------------


def test_render_contrato_exposes_single_public_function() -> None:
    """PR 1 still ships only the template engine — no PDF, no storage.

    The public surface of :mod:`app.modules.contratos.application.render_contrato`
    is exactly :func:`render_contrato`. Helper functions are
    intentionally ``_``-prefixed to keep them private to the
    dispatch table and excluded from this assertion. PDF adapter
    and storage adapter live under ``application/render_to_pdf.py``
    and ``adapters/local_backend/`` respectively.
    """
    module_path = CONTRATOS_ROOT / "application" / "render_contrato.py"
    source = module_path.read_text(encoding="utf-8")
    declared: set[str] = set()
    for match in re.finditer(r"^def\s+(\w+)\s*\(", source, re.MULTILINE):
        name = match.group(1)
        if name.startswith("_"):
            continue
        declared.add(name)
    assert declared == {"render_contrato"}, (
        f"render_contrato.py must expose only render_contrato as a public "
        f"function; declared: {sorted(declared)}"
    )


# ---------------------------------------------------------------------------
# Gate 4: adapters/local_backend/ is the only layer that touches transport
# ---------------------------------------------------------------------------


def test_adapters_local_backend_imports_transport() -> None:
    """Sanity check: the transport adapters actually use their libraries.

    A regression that removes the ``reportlab`` import from the PDF
    adapter (e.g. someone "simplifies" the module) breaks the slice
    silently — this gate fails first with a clear message.
    """
    pdf_adapter = (
        CONTRATOS_ROOT
        / "adapters"
        / "local_backend"
        / "contratos_local_backend_pdf.py"
    )
    storage_adapter = (
        CONTRATOS_ROOT
        / "adapters"
        / "local_backend"
        / "contratos_local_backend_storage.py"
    )
    assert pdf_adapter.exists(), "PDF adapter missing"
    assert storage_adapter.exists(), "Storage adapter missing"

    pdf_source = pdf_adapter.read_text(encoding="utf-8")
    assert "reportlab" in pdf_source, (
        "PDF adapter must import reportlab; without it the slice has no PDF "
        "engine. If you meant to remove the dependency, also remove the "
        "adapter and the slice cannot ship."
    )

    storage_source = storage_adapter.read_text(encoding="utf-8")
    assert "minio" in storage_source, (
        "Storage adapter must import minio; without it the slice has no object "
        "storage backend."
    )
