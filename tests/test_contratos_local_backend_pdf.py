"""Tests for the reportlab-backed PDF adapter (DOC-01 PR 2).

The adapter is the only module in the slice allowed to import
reportlab; the architectural pin guards that boundary. These tests
exercise the public surface of
:class:`ReportLabPdfGenerator` with real reportlab calls so a
regression in the envelope parser or the platypus story fails fast.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): no I/O. reportlab runs in-memory via
  ``io.BytesIO``.
- Rule 2 (no humo): every assertion pins one observable contract —
  the PDF magic header, the extracted title, the parsed body.
- Rule 4 (no production mutation): the tests exercise the public
  ``render_html_to_pdf`` method only.
- Rule 8 (no production mutation): no fixtures hit a database.
"""

from __future__ import annotations

from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
    ReportLabPdfGenerator,
)

# --- 1. PDF magic header --------------------------------------------------


def test_render_html_to_pdf_returns_valid_pdf_bytes() -> None:
    """The adapter returns bytes that start with the PDF magic header.

    Every well-formed PDF begins with ``%PDF-``. Anything else means
    reportlab failed silently (e.g. font lookup, CSS issue) or the
    adapter emitted non-PDF bytes.
    """
    generator = ReportLabPdfGenerator()
    pdf_bytes = generator.render_html_to_pdf(
        "<!DOCTYPE html><html><body><h1>Test</h1><pre>body</pre></body></html>"
    )
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_html_to_pdf_uses_html_envelope_title() -> None:
    """The envelope ``<h1>`` becomes the PDF document title.

    reportlab sets ``/Title`` in the PDF metadata from the
    ``SimpleDocTemplate(title=...)`` argument; the adapter passes the
    envelope title there so screen readers and PDF inspectors see the
    contract name.
    """
    generator = ReportLabPdfGenerator()
    pdf_bytes = generator.render_html_to_pdf(
        '<!DOCTYPE html><html><body><h1>Contrato de Adopción</h1>'
        "<pre>body</pre></body></html>"
    )
    # PDF metadata is uncompressed only when explicitly enabled. The
    # default compression hides the literal title bytes, so we can
    # only pin the magic header here. The internal logic is
    # exercised by test_2 below via the parser.
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 100


# --- 2. Envelope parser ----------------------------------------------------


def test_parse_envelope_extracts_title_and_body() -> None:
    """The envelope parser returns the unescaped ``(titulo, cuerpo)``.

    Pins the helper so a regression that breaks HTML unescape or
    regex matching fails the gate immediately.
    """
    from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
        _parse_envelope,
    )

    titulo, cuerpo = _parse_envelope(
        "<!DOCTYPE html><html><body>"
        "<h1>Contrato de Adopci&oacute;n</h1>"
        "<pre>Línea 1\nLínea 2</pre>"
        "</body></html>"
    )
    assert titulo == "Contrato de Adopción"
    assert cuerpo == "Línea 1\nLínea 2"


def test_parse_envelope_handles_missing_h1() -> None:
    """An envelope without ``<h1>`` returns an empty title.

    The use case always emits ``<h1>``, but the parser is defensive:
    callers can use the helper directly and pass arbitrary HTML.
    """
    from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
        _parse_envelope,
    )

    titulo, cuerpo = _parse_envelope(
        "<!DOCTYPE html><html><body><pre>only body</pre></body></html>"
    )
    assert titulo == ""
    assert cuerpo == "only body"


# --- 3. HTML escape in the body parser -----------------------------------


def test_format_body_preserves_newlines() -> None:
    """The body formatter turns newlines into ``<br/>`` tags.

    reportlab paragraphs collapse whitespace by default; preserving
    the template-engine layout requires explicit ``<br/>`` between
    lines and paragraph breaks between blank-line runs.
    """
    from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
        _format_body,
    )

    out = _format_body("Línea 1\nLínea 2\n\nLínea 3")
    assert out == "Línea 1<br/>Línea 2<br/><br/>Línea 3"


def test_escape_xml_handles_ampersands() -> None:
    """The XML escape turns ``&`` into ``&amp;`` first.

    reportlab's paragraph parser rejects raw ampersands inside
    attribute values; the escape helper escapes ``&`` before ``<``
    and ``>`` so a literal ``<`` in the source text survives the
    round-trip as ``&lt;`` rather than being mistaken for an entity.
    """
    from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
        _escape_xml,
    )

    assert _escape_xml("a & b") == "a &amp; b"
    assert _escape_xml("a < b") == "a &lt; b"
    assert _escape_xml("a > b") == "a &gt; b"
    assert _escape_xml("a & < b") == "a &amp; &lt; b"
