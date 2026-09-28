"""Reportlab-backed PDF generator for the contratos slice (DOC-01 CP3, #850).

Implements the CP1 :class:`~app.modules.contratos.ports.contratos_pdf_port.ContratosPdfPort`
with reportlab (platypus). This adapter is the ONLY module in the
contratos slice allowed to import reportlab — the architectural pin
test (``tests/test_slice_contratos_architecture.py``, AGENTS.md §33.4)
fails if the import leaks into ``domain/``, ``ports/`` or
``application/``.

Rendering strategy: a faithful-enough text rendering, NOT a full HTML
parser. The CP2 use case emits a fixed, already-escaped HTML envelope
(``<h1>`` title + ``<pre>`` body); this adapter extracts the title and
the pre-formatted body with two narrow regexes, unescapes the HTML
entities, and feeds the text to platypus ``Paragraph`` flowables.
Newlines in the body become ``<br/>`` so the template engine's layout
survives (reportlab collapses whitespace by default).

Failure mode: reportlab exceptions are wrapped (never swallowed) in
:class:`ContratosPdfRenderError` so callers of the port see one
documented adapter-level exception and keep the original diagnostic
via ``__cause__``.
"""

from __future__ import annotations

import html as _html
import io
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

#: Fallback document title when the envelope carries no ``<h1>``.
_DEFAULT_TITLE = "Contrato"

#: Minimum body font size for the ``<pre>`` content, mirroring the
#: envelope's ``line-height: 1.5`` readability intent.
_BODY_FONT_SIZE = 10.5
_BODY_LEADING = 15.75


class ContratosPdfRenderError(RuntimeError):
    """Raised when the reportlab engine fails to render the envelope.

    Wraps (never swallows) the underlying reportlab exception; the
    original error stays reachable via ``__cause__``. Subclasses
    :class:`RuntimeError` so a caller that only catches transport
    failures still sees it, while a caller that inspects the exception
    type can distinguish "the PDF backend failed" from "the inputs
    were invalid" (the use case raises its own
    :class:`~app.modules.contratos.application.render_to_pdf.RenderToPdfValidationError`
    before the port is ever called).
    """


_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)


def _parse_envelope(html: str) -> tuple[str, str]:
    """Extract the unescaped ``(titulo, cuerpo)`` pair from the envelope.

    The CP2 use case HTML-escapes both the title and the body before
    wrapping them, so this parser unescapes the captured groups back
    to plain text. A missing ``<h1>`` yields an empty title (the
    document falls back to :data:`_DEFAULT_TITLE`); a missing
    ``<pre>`` yields an empty body (the PDF still renders, with the
    title alone).
    """
    h1_match = _H1_RE.search(html)
    pre_match = _PRE_RE.search(html)
    titulo = _html.unescape(h1_match.group(1)) if h1_match else ""
    cuerpo = _html.unescape(pre_match.group(1)) if pre_match else ""
    return titulo.strip(), cuerpo.strip()


def _escape_xml(text: str) -> str:
    """Escape ``text`` for the reportlab paragraph mini-XML-parser.

    ``&`` is escaped FIRST so an ``&lt;`` entity produced by the CP2
    escape pass survives as the literal text ``<`` instead of being
    re-interpreted as markup by reportlab.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_body(text: str) -> str:
    """Convert plain-text newlines into reportlab paragraph markup.

    Single newlines become ``<br/>`` (reportlab collapses ``\\n``);
    blank-line runs become paragraph breaks (``<br/><br/>``) so the
    template engine's stanza layout is preserved.
    """
    return _escape_xml(text).replace("\n", "<br/>")


class ReportLabPdfGenerator:
    """Concrete :class:`ContratosPdfPort` backed by reportlab platypus.

    Renders the CP2 HTML envelope into a one-column A4 document:
    the envelope ``<h1>`` becomes the page title (and the PDF
    metadata ``/Title``), and the ``<pre>`` body becomes the
    pre-formatted contract text. Stateless: one instance can serve
    every render in the process.
    """

    def render_html_to_pdf(self, html: str) -> bytes:
        """Render ``html`` to PDF and return the raw bytes.

        Implements the CP1 port contract. Raises
        :class:`ContratosPdfRenderError` when reportlab fails;
        never returns partially-written buffer content.
        """
        try:
            titulo, cuerpo = _parse_envelope(html)
            buffer = io.BytesIO()
            document = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                title=titulo or _DEFAULT_TITLE,
                leftMargin=25 * mm,
                rightMargin=25 * mm,
                topMargin=25 * mm,
                bottomMargin=25 * mm,
            )
            story = self._build_story(titulo, cuerpo)
            document.build(story)
            return buffer.getvalue()
        except ContratosPdfRenderError:
            raise
        except Exception as exc:
            raise ContratosPdfRenderError(  # noqa: TRY003 — wrapped reportlab diagnostic
                f"reportlab no pudo renderizar el PDF del contrato: {exc}"
            ) from exc

    def _build_story(self, titulo: str, cuerpo: str) -> list[Flowable]:
        """Build the platypus story for one contract document.

        Kept as a method (not a module function) so the layout choices
        stay co-located with the render call they serve.
        """
        styles = getSampleStyleSheet()
        title_style = styles["Title"]
        body_style = ParagraphStyle(
            "ContratoBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=_BODY_FONT_SIZE,
            leading=_BODY_LEADING,
        )
        story: list[Flowable] = [
            Paragraph(_escape_xml(titulo or _DEFAULT_TITLE), title_style),
            Spacer(1, 6 * mm),
        ]
        if cuerpo:
            for stanza in cuerpo.split("\n\n"):
                story.append(
                    Paragraph(_format_body(stanza), body_style),
                )
                story.append(Spacer(1, 3 * mm))
        return story


__all__ = ["ContratosPdfRenderError", "ReportLabPdfGenerator"]
