"""PDF generator adapter using reportlab (DOC-01 PR 2, #56).

The :class:`ContratosPdfGeneratorPort` Protocol in
``ports/contratos_pdf_port.py`` is implemented here against reportlab
4.x. The use case produces a minimal HTML envelope via
``application/render_to_pdf._wrap_html``; this adapter extracts the
``<h1>`` and ``<pre>`` blocks and renders them with the reportlab
platypus engine.

The adapter is the only module in the slice allowed to import
``reportlab``. The pin arquitectónico fails immediately if a sibling
file (``domain``, ``ports`` or ``application``) imports reportlab.
"""

from __future__ import annotations

import html as _html
import io
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

#: Match the ``<h1>...</h1>`` block emitted by the use case.
_H1_RE = re.compile(r"<h1>(?P<titulo>.*?)</h1>", re.DOTALL)
#: Match the ``<pre>...</pre>`` block emitted by the use case.
_PRE_RE = re.compile(r"<pre>(?P<cuerpo>.*?)</pre>", re.DOTALL)


def _parse_envelope(html: str) -> tuple[str, str]:
    """Extract ``(titulo, cuerpo)`` from the standard contratos envelope.

    The envelope is produced by
    :func:`app.modules.contratos.application.render_to_pdf._wrap_html`,
    so the regex is intentionally narrow — it does not need to handle
    arbitrary HTML. Both fields are HTML-unescaped so the reportlab
    paragraph writer sees the original characters the operator typed.
    """
    titulo_match = _H1_RE.search(html)
    cuerpo_match = _PRE_RE.search(html)
    titulo = (
        _html.unescape(titulo_match.group("titulo")) if titulo_match else ""
    )
    cuerpo = (
        _html.unescape(cuerpo_match.group("cuerpo")) if cuerpo_match else html
    )
    return titulo.strip(), cuerpo


class ReportLabPdfGenerator:
    """reportlab-backed implementation of :class:`ContratosPdfGeneratorPort`.

    Produces an A4 PDF document with the envelope title as a centered
    heading and the body as a single monospace-style paragraph (the
    ``<pre>`` from the envelope). Whitespace inside the body is
    preserved verbatim because reportlab paragraphs collapse runs of
    spaces by default — the stylesheet is configured to honor
    ``white-space: pre-wrap`` via the ``pre`` HTML tag below.
    """

    def render_html_to_pdf(self, html: str) -> bytes:
        """Render ``html`` to a PDF document and return the bytes."""
        titulo, cuerpo = _parse_envelope(html)
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=titulo or "Contrato",
        )
        styles = getSampleStyleSheet()
        story: list[Flowable] = []
        if titulo:
            story.append(Paragraph(_escape_xml(titulo), styles["Title"]))
            story.append(Spacer(1, 1.2 * cm))
        # ``<pre>`` keeps the line breaks the template engine emitted.
        body_html = f"<para leftindent='0'>{_format_body(cuerpo)}</para>"
        story.append(Paragraph(_escape_xml(body_html), styles["Code"]))
        doc.build(story)
        return buffer.getvalue()


def _escape_xml(text: str) -> str:
    """Escape XML characters that reportlab's paragraph parser rejects."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_body(cuerpo: str) -> str:
    """Convert plain-text newlines to reportlab ``<br/>`` tags.

    reportlab's ``<para>`` collapses whitespace by default; preserving
    the line layout from the template engine requires turning every
    newline into an explicit break tag. Double newlines become
    paragraph breaks.
    """
    escaped = _escape_xml(cuerpo)
    paragraphs = escaped.split("\n\n")
    rendered: list[str] = []
    for paragraph in paragraphs:
        rendered.append(paragraph.replace("\n", "<br/>"))
    return "<br/><br/>".join(rendered)


__all__ = ["ReportLabPdfGenerator"]
