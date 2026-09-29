"""Tests for the reportlab-backed PDF adapter (DOC-01 CP3, issue #850).

The adapter is the only module in the slice allowed to import
reportlab; the architectural pin test
(``tests/test_slice_contratos_architecture.py``, AGENTS.md §33.4)
guards that boundary. These tests exercise the public surface of
:class:`ReportLabPdfGenerator` with real reportlab calls so a
regression in the envelope parser or the platypus story fails fast,
plus the CP2+CP3 wiring: :func:`render_to_pdf` with the REAL adapter
must produce PDF bytes end-to-end (the storage leg of the old #795
full flow is CP4 and stays out of this file).

Test type: **unit** (apap-testing-strategy §3) — reportlab runs
in-memory via ``io.BytesIO``; no DB, no network, no filesystem.

web-tdd-philosophy rules honoured: fixture gate (module-level
constants build every input; no luck-of-data), no humo (every atom
pins one observable contract: magic header, size, length equality,
parser output, exception type), three paths (happy render / sad
render failure wrapped as the documented adapter exception / edge
envelope without ``<h1>`` and markup-laden body), refactor-safety
(asserts outcomes, not reportlab call order), no production mutation.
"""

from __future__ import annotations

import pytest

from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
    ContratosPdfRenderError,
    ReportLabPdfGenerator,
    _escape_xml,
    _format_body,
    _parse_envelope,
)
from app.modules.contratos.application.render_to_pdf import render_to_pdf
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort

# --- Constants / fixture envelope -----------------------------------------

#: Envelope in the exact shape the CP2 use case emits (HTML-escaped
#: body). Values are obviously fake and gitleaks-safe.
ENVELOPE = (
    "<!DOCTYPE html>"
    '<html lang="es">'
    "<head><meta charset=\"utf-8\"><title>Contrato de Adopcion</title></head>"
    "<body>"
    "<h1>Contrato de Adopcion</h1>"
    "<pre>Animal: Toby&#10;Adoptante: Marta</pre>"
    "</body>"
    "</html>"
)

#: Minimum size for a real A4 one-page PDF (a trivial/garbage output
#: would be far smaller than any reportlab document).
MIN_PDF_SIZE = 500


# --- 1. Port conformance ----------------------------------------------------


def test_adapter_satisfies_contratos_pdf_port() -> None:
    """The adapter is a runtime :class:`ContratosPdfPort` instance.

    Pins the CP3 contract: the use case accepts the adapter because it
    implements the Protocol, not because of inheritance.
    """
    generator = ReportLabPdfGenerator()
    assert isinstance(generator, ContratosPdfPort)


# --- 2. Happy path: real reportlab rendering --------------------------------


def test_render_html_to_pdf_returns_valid_pdf_bytes() -> None:
    """The adapter returns bytes that start with the PDF magic header.

    Every well-formed PDF begins with ``%PDF-``. Anything else means
    reportlab failed silently or the adapter emitted non-PDF bytes.
    """
    generator = ReportLabPdfGenerator()
    pdf_bytes = generator.render_html_to_pdf(ENVELOPE)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_html_to_pdf_produces_non_trivial_output() -> None:
    """The rendered PDF is a real document, not a stub buffer.

    A one-page reportlab A4 document with fonts and page resources is
    comfortably above :data:`MIN_PDF_SIZE`; an empty or truncated
    buffer is not.
    """
    generator = ReportLabPdfGenerator()
    pdf_bytes = generator.render_html_to_pdf(ENVELOPE)
    assert len(pdf_bytes) > MIN_PDF_SIZE


def test_render_html_to_pdf_is_deterministic_for_identical_input() -> None:
    """Identical input yields identical-length output.

    reportlab embeds a creation timestamp and document ID, so the raw
    bytes may differ run to run; the document SIZE is the stable
    observable for identical input. A regression that injects
    variable-length state (random font subsetting, unchecked error
    pages) breaks this pin.
    """
    generator = ReportLabPdfGenerator()
    first = generator.render_html_to_pdf(ENVELOPE)
    second = generator.render_html_to_pdf(ENVELOPE)
    assert len(first) == len(second)
    assert first[:5] == b"%PDF-"
    assert second[:5] == b"%PDF-"


def test_render_html_to_pdf_renders_markup_laden_body_without_error() -> None:
    """An already-escaped markup payload renders as text, not as tags.

    The CP2 use case HTML-escapes variable values, so the envelope
    body can contain ``&lt;script&gt;`` entities; the adapter must
    unescape them for the parser and re-escape them for the reportlab
    XML mini-parser. A regression that feeds raw angle brackets to
    reportlab breaks the platypus build.
    """
    envelope = (
        "<!DOCTYPE html><html><body><h1>Contrato</h1>"
        "<pre>&lt;script&gt;alert(1)&lt;/script&gt;</pre>"
        "</body></html>"
    )
    generator = ReportLabPdfGenerator()
    pdf_bytes = generator.render_html_to_pdf(envelope)
    assert pdf_bytes[:5] == b"%PDF-"


# --- 3. Envelope parser (edge paths) ----------------------------------------


def test_parse_envelope_extracts_title_and_body() -> None:
    """The envelope parser returns the unescaped ``(titulo, cuerpo)``.

    Pins the helper so a regression that breaks HTML unescape or
    regex matching fails the gate immediately.
    """
    titulo, cuerpo = _parse_envelope(
        "<!DOCTYPE html><html><body>"
        "<h1>Contrato de Adopci&oacute;n</h1>"
        "<pre>L&#237;nea 1\nL&#237;nea 2</pre>"
        "</body></html>"
    )
    assert titulo == "Contrato de Adopción"
    assert cuerpo == "Línea 1\nLínea 2"


def test_parse_envelope_handles_missing_h1() -> None:
    """An envelope without ``<h1>`` yields an empty title, body intact.

    The use case always emits ``<h1>``, but the parser is defensive:
    the title falls back to the document default and the body is
    still rendered.
    """
    titulo, cuerpo = _parse_envelope(
        "<!DOCTYPE html><html><body><pre>only body</pre></body></html>"
    )
    assert titulo == ""
    assert cuerpo == "only body"


def test_format_body_preserves_newlines() -> None:
    """The body formatter turns newlines into ``<br/>`` tags.

    reportlab paragraphs collapse whitespace by default; preserving
    the template-engine layout requires explicit ``<br/>`` between
    lines and paragraph breaks between blank-line runs.
    """
    out = _format_body("Línea 1\nLínea 2\n\nLínea 3")
    assert out == "Línea 1<br/>Línea 2<br/><br/>Línea 3"


def test_escape_xml_handles_ampersands_first() -> None:
    """The XML escape turns ``&`` into ``&amp;`` first.

    reportlab's paragraph mini-parser rejects raw ampersands; the
    escape helper escapes ``&`` before ``<`` and ``>`` so a literal
    ``<`` in the source text survives the round-trip as ``&lt;``
    rather than being mistaken for an entity.
    """
    assert _escape_xml("a & b") == "a &amp; b"
    assert _escape_xml("a < b") == "a &lt; b"
    assert _escape_xml("a > b") == "a &gt; b"
    assert _escape_xml("a & < b") == "a &amp; &lt; b"


# --- 4. Sad path: adapter-level error wrapping -------------------------------


def test_reportlab_failure_raises_contratos_pdf_render_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reportlab failures surface as the documented adapter exception.

    The adapter wraps (never swallows) transport-level failures in
    :class:`ContratosPdfRenderError`; the original reportlab error
    stays reachable via ``__cause__`` so operators keep the real
    diagnostic.
    """
    from app.modules.contratos.adapters.local_backend import (
        contratos_local_backend_pdf as adapter_module,
    )

    class _ExplodingTemplate:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def build(self, story: object, **kwargs: object) -> None:
            raise RuntimeError("reportlab exploded")

    monkeypatch.setattr(adapter_module, "SimpleDocTemplate", _ExplodingTemplate)
    generator = ReportLabPdfGenerator()
    with pytest.raises(ContratosPdfRenderError, match="reportlab exploded") as excinfo:
        generator.render_html_to_pdf(ENVELOPE)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


# --- 5. CP2 + CP3 wiring: use case with the REAL adapter ---------------------


def test_render_to_pdf_with_real_adapter_produces_pdf_bytes() -> None:
    """The CP2 use case wired to the CP3 adapter emits a valid PDF.

    Full-pipeline pin (PDF leg of the old #795 full flow): domain
    entities → :func:`render_to_pdf` → :class:`ReportLabPdfGenerator`
    → raw PDF bytes. The storage leg (CP4) is exercised by its own
    PR's tests.
    """
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Animal: {{animal.nombre}}\n"
            "Adoptante: {{persona.nombre}} {{persona.apellidos}}\n"
            "{% if animal.edad_meses >= 6 %}"
            "Cláusula de esterilización."
            "{% endif %}"
        ),
    )
    solicitud = SolicitudContrato(
        variables={
            "animal.nombre": "Toby",
            "persona.nombre": "Marta",
            "persona.apellidos": "García",
            "animal.edad_meses": "12",
        },
        tipo=TipoContrato.ADOPCION,
    )
    pdf_bytes = render_to_pdf(
        plantilla, solicitud, ReportLabPdfGenerator(), titulo="Contrato de Adopción"
    )
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > MIN_PDF_SIZE
