"""Tests for the DOC-01 CP-2 ``render_to_pdf`` use case (issue #850).

Test type: **Application unit (hexagonal)** — the slice talks to the
:class:`ContratosPdfPort` Protocol injected via parameter; the stub
records calls in memory so the use case stays transport-free.
web-tdd-philosophy rules honoured: fixture gate (no I/O/DB/network),
cardinality (port called exactly once), no humo (bytes/envelope/
message pinned), three paths (happy / validation sad path / port
failure + escaping edge paths), no production mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.application.render_to_pdf import (
    RenderToPdfValidationError,
    render_to_pdf,
)
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato

# --- 1. Stub generator ----------------------------------------------------


@dataclass
class _RecordingGenerator:
    """Stub generator that records the HTML it receives.

    Returns a deterministic ``b"%PDF-stub-bytes"`` so the bytes
    equality can pin the port contract (the use case must pass the
    port's bytes through untouched).
    """

    recorded_html: list[str] = field(default_factory=list)
    return_value: bytes = b"%PDF-stub-bytes"

    def render_html_to_pdf(self, html: str) -> bytes:
        self.recorded_html.append(html)
        return self.return_value


@dataclass
class _ExplodingGenerator:
    """Stub generator that fails the way a real adapter would."""

    error: Exception = RuntimeError("pdf backend exploded")
    called: bool = False

    def render_html_to_pdf(self, html: str) -> bytes:
        self.called = True
        raise self.error


# --- 2. Pure text rendering still works -----------------------------------


def test_render_contrato_still_returns_text_only() -> None:
    """The CP-1 ``render_contrato`` still emits plain text.

    Pinning this guards against refactors that collapse the text and
    PDF paths into one.
    """
    plantilla = Plantilla(
        tipo=TipoContrato.ENTRADA,
        cuerpo="Hola {{animal.nombre}}.",
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Luna"},
        tipo=TipoContrato.ENTRADA,
    )
    assert render_contrato(plantilla, solicitud) == "Hola Luna."


# --- 3. render_to_pdf: envelope + delegation ------------------------------


def test_render_to_pdf_delegates_to_injected_generator() -> None:
    """``render_to_pdf`` builds the envelope and delegates to the port.

    Pins the title, the rendered body, and the exact bytes passthrough
    from the port.
    """
    generator = _RecordingGenerator()
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo="Animal: {{animal.nombre}}.\n",
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Toby"},
        tipo=TipoContrato.ADOPCION,
    )
    pdf_bytes = render_to_pdf(
        plantilla,
        solicitud,
        generator,
        titulo="Contrato de Adopción",
    )

    assert pdf_bytes == generator.return_value
    assert len(generator.recorded_html) == 1
    html = generator.recorded_html[0]
    # html.escape only escapes <, >, &, ", ' — Unicode chars pass through.
    assert "<h1>Contrato de Adopción</h1>" in html
    assert "Animal: Toby." in html


def test_render_to_pdf_escapes_html_metacharacters_in_variables() -> None:
    """A variable value with HTML markup is escaped, not interpreted.

    Same stdlib ``html.escape`` rule the envelope applies to the
    title.
    """
    generator = _RecordingGenerator()
    plantilla = Plantilla(
        tipo=TipoContrato.ENTRADA,
        cuerpo="Nota: {{animal.nota}}.",
    )
    solicitud = SolicitudContrato(
        variables={"animal.nota": "<script>alert(1)</script>"},
        tipo=TipoContrato.ENTRADA,
    )
    render_to_pdf(plantilla, solicitud, generator, titulo="x")

    html = generator.recorded_html[0]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_to_pdf_default_title_is_contrato() -> None:
    """When the caller omits ``titulo``, the envelope renders ``Contrato``."""
    generator = _RecordingGenerator()
    plantilla = Plantilla(
        tipo=TipoContrato.ENTRADA,
        cuerpo="x",
    )
    solicitud = SolicitudContrato(
        variables={},
        tipo=TipoContrato.ENTRADA,
    )
    render_to_pdf(plantilla, solicitud, generator)

    html = generator.recorded_html[0]
    assert "<h1>Contrato</h1>" in html


def test_render_to_pdf_respects_conditional_blocks() -> None:
    """Conditional clauses inside the template still gate the body (CP-1)."""
    generator = _RecordingGenerator()
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Animal: {{animal.nombre}}\n"
            "{% if animal.edad_meses >= 6 %}"
            "Cláusula de esterilización."
            "{% endif %}"
        ),
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Toby", "animal.edad_meses": "12"},
        tipo=TipoContrato.ADOPCION,
    )
    render_to_pdf(plantilla, solicitud, generator)

    html = generator.recorded_html[0]
    assert "Cláusula de esterilización." in html

    cachorro = SolicitudContrato(
        variables={"animal.nombre": "Bimba", "animal.edad_meses": "3"},
        tipo=TipoContrato.ADOPCION,
    )
    render_to_pdf(plantilla, cachorro, generator)
    html = generator.recorded_html[1]
    assert "Cláusula de esterilización." not in html


# --- 4. Sad path: contract validation BEFORE the port ---------------------


def test_render_to_pdf_rejects_blank_template_before_port() -> None:
    """A blank template body is a legacy-fidelity bug: no contract text.

    Rejected with a clear error BEFORE the port is called.
    """
    generator = _RecordingGenerator()
    plantilla = Plantilla(tipo=TipoContrato.ENTRADA, cuerpo="   ")
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Luna"},
        tipo=TipoContrato.ENTRADA,
    )

    with pytest.raises(RenderToPdfValidationError, match="plantilla"):
        render_to_pdf(plantilla, solicitud, generator)

    assert generator.recorded_html == []


def test_render_to_pdf_rejects_blank_titulo_before_port() -> None:
    """A blank ``titulo`` would render an unidentifiable contract PDF."""
    generator = _RecordingGenerator()
    plantilla = Plantilla(tipo=TipoContrato.ENTRADA, cuerpo="Texto.")
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Luna"},
        tipo=TipoContrato.ENTRADA,
    )

    with pytest.raises(RenderToPdfValidationError, match="titulo"):
        render_to_pdf(plantilla, solicitud, generator, titulo="  ")

    assert generator.recorded_html == []


# --- 5. Edge path: port failure propagates --------------------------------


def test_render_to_pdf_port_error_propagates_unchanged() -> None:
    """A failure raised by the port reaches the caller untranslated.

    Orchestration only: no swallow, no wrap — the CP-3 route decides
    the HTTP mapping.
    """
    generator = _ExplodingGenerator(error=RuntimeError("pdf backend exploded"))
    plantilla = Plantilla(tipo=TipoContrato.ENTRADA, cuerpo="Texto.")
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Luna"},
        tipo=TipoContrato.ENTRADA,
    )

    with pytest.raises(RuntimeError, match="pdf backend exploded"):
        render_to_pdf(plantilla, solicitud, generator)

    assert generator.called is True


# --- 6. Architecture pin: application stays reportlab-free ----------------


_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))", re.MULTILINE)


def test_render_to_pdf_module_never_imports_reportlab() -> None:
    """The use case source never imports reportlab (AGENTS.md §33.4).

    Source-level check (same technique as the slice pin test) so it
    stays deterministic regardless of test session import order.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "modules"
        / "contratos"
        / "application"
        / "render_to_pdf.py"
    ).read_text(encoding="utf-8")

    imported = {m.group(1) or m.group(2) for m in _IMPORT_RE.finditer(source)}
    leaks = [m for m in imported if m == "reportlab" or m.startswith("reportlab.")]
    assert not leaks, f"render_to_pdf.py leaked PDF-adapter imports: {leaks}"
