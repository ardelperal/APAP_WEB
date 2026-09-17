"""Use case: render one contract template to PDF bytes (DOC-01 PR 2).

This use case wires the PR-1 text engine (:func:`render_contrato`)
with the PR-2 PDF generator port (:class:`ContratosPdfGeneratorPort`)
to produce a PDF byte string ready for storage. It does NOT touch the
filesystem, MinIO or weasyprint directly — those concerns belong to
the adapter under ``adapters/local_backend/``.

Flow:

1. Render the template body to plain text via :func:`render_contrato`.
2. Wrap the text in a minimal HTML envelope with CSS for contracts.
3. HTML-escape the rendered text so a malicious variable value
   (``<script>alert(1)</script>``) cannot inject markup into the PDF.
4. Delegate the HTML→PDF conversion to the injected port.

The use case is pure: it accepts a :class:`ContratosPdfGeneratorPort`
via dependency injection, so tests can substitute a deterministic stub.
"""

from __future__ import annotations

import html as _html

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.ports.contratos_pdf_port import (
    ContratosPdfGeneratorPort,
)

#: Minimal HTML wrapper used for the PDF generator. Kept inline (not a
#: template file) because every contratos slice generates PDF through
#: this exact envelope — adding a template loader is out of scope for
#: PR 2. The CSS targets the screen layout weasyprint renders to A4.
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{titulo}</title>
<style>
  body {{ font-family: serif; max-width: 720px; margin: 2em auto; padding: 0 1.5em; color: #111; }}
  h1 {{ text-align: center; font-size: 1.4em; margin-bottom: 1.5em; }}
  pre {{ font-family: inherit; white-space: pre-wrap; line-height: 1.5; }}
</style>
</head>
<body>
<h1>{titulo}</h1>
<pre>{cuerpo}</pre>
</body>
</html>
"""


def _wrap_html(texto: str, *, titulo: str) -> str:
    """Wrap ``texto`` in the standard contratos HTML template.

    The body is HTML-escaped so a variable value containing markup is
    rendered as text inside the PDF rather than executed as HTML. The
    title is HTML-escaped for the same reason.
    """
    return _HTML_TEMPLATE.format(
        titulo=_html.escape(titulo),
        cuerpo=_html.escape(texto),
    )


def render_to_pdf(
    plantilla: Plantilla,
    solicitud: SolicitudContrato,
    pdf_port: ContratosPdfGeneratorPort,
    *,
    titulo: str = "Contrato",
) -> bytes:
    """Render ``plantilla`` for ``solicitud`` and return PDF bytes.

    The ``titulo`` argument controls the H1 rendered in the PDF. It
    defaults to "Contrato"; callers (PR 3 route handler) override it
    per contract type (``Contrato de Adopción``, etc.).

    The returned bytes are the raw PDF document and can be passed
    directly to :meth:`ContratosStoragePort.put_pdf`.
    """
    texto = render_contrato(plantilla, solicitud)
    html = _wrap_html(texto, titulo=titulo)
    return pdf_port.render_html_to_pdf(html)


__all__ = ["render_to_pdf"]
