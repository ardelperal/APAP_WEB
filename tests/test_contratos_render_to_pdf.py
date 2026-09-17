"""Tests for the DOC-01 PR-2 ``render_to_pdf`` use case.

The use case depends on a :class:`ContratosPdfGeneratorPort` Protocol,
injected via parameter. Tests use a deterministic stub that records
calls and returns fixed bytes, so the use case stays hermetic.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no I/O, no DB, no network. The stub is a
  plain dataclass with one method.
- Rule 2 (no humo): every assertion pins one observable contract —
  the bytes returned, the HTML envelope passed, the title rendered.
- Rule 4 (no production mutation): no fixtures hit a database.
- Rule 8 (no production mutation): the test exercises the public
  surface of the use case only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.application.render_to_pdf import render_to_pdf
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato

# --- 1. Stub generator ----------------------------------------------------


@dataclass
class _RecordingGenerator:
    """Stub generator that records the HTML it receives.

    Returns a deterministic ``b"%PDF-stub-bytes"`` so the use case
    bytes equality can pin the port contract.
    """

    recorded_html: list[str] = field(default_factory=list)
    return_value: bytes = b"%PDF-stub-bytes"

    def render_html_to_pdf(self, html: str) -> bytes:
        self.recorded_html.append(html)
        return self.return_value


# --- 2. Pure text rendering still works ----------------------------------


def test_render_contrato_still_returns_text_only() -> None:
    """The PR-1 ``render_contrato`` still emits plain text.

    PR 2 adds the PDF layer on top; the underlying text engine is
    unchanged. Pinning this guards against accidental refactors that
    collapse the text and PDF paths into one.
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


# --- 3. render_to_pdf: envelope + delegation -----------------------------


def test_render_to_pdf_delegates_to_injected_generator() -> None:
    """``render_to_pdf`` builds the envelope and delegates to the port.

    The generator stub records the HTML it receives; the test pins
    the title and the escaped body inside that envelope.
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

    The use case HTML-escapes the rendered text so a malicious
    variable (``<script>alert(1)</script>``) cannot inject script
    tags into the PDF envelope. The escape rule is the same stdlib
    ``html.escape`` that the envelope itself uses for the title.
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
    """When the caller omits ``titulo``, the envelope renders ``Contrato``.

    Pins the default so PR 3 route handlers can rely on a sensible
    H1 for one-shot smoke tests.
    """
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
    """Conditional clauses inside the template still gate the body.

    Pins the integration with PR 1: the use case must pass the
    post-render text (with conditions evaluated) to the envelope.
    """
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
