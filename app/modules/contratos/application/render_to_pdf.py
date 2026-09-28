"""Use case: render one contract template to PDF bytes (DOC-01 CP-2).

Wires the CP-1 text engine (:func:`render_contrato`) with the CP-1
PDF port (:class:`ContratosPdfPort`) to produce a PDF byte string
ready for storage. It does NOT touch reportlab, the filesystem or
object storage directly — reportlab belongs to the CP-3 adapter under
``adapters/local_backend/`` (AGENTS.md §33.4).

Flow:

1. Validate the contract inputs (blank template body or blank title
   are rejected with :class:`RenderToPdfValidationError` BEFORE the
   port is called — a blank contract PDF is a legacy-fidelity bug,
   not a rendering concern).
2. Render the template body to plain text via :func:`render_contrato`.
3. Wrap the text in a minimal HTML envelope, HTML-escaping both the
   rendered text and the title so a variable value containing markup
   (``<script>alert(1)</script>``) cannot inject tags into the PDF.
4. Delegate the HTML→PDF conversion to the injected port and return
   its bytes untouched.

The use case is pure: it accepts a :class:`ContratosPdfPort` via
dependency injection, so tests substitute a deterministic stub and the
CP-3 route wires the real reportlab adapter.
"""

from __future__ import annotations

import html as _html

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort

#: Minimal HTML wrapper used for the PDF generator. Kept inline (not a
#: template file) because every contratos slice generates PDF through
#: this exact envelope — adding a template loader is out of scope for
#: CP-2.
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


class RenderToPdfValidationError(ValueError):
    """Raised when the render-to-PDF inputs fail the contract checks.

    Subclasses :class:`ValueError` so legacy ``except ValueError``
    clauses keep working. Raised BEFORE the port is called so a bad
    payload never reaches the PDF adapter.
    """


def _require_non_blank(value: str, field_name: str) -> str:
    """Return ``value`` stripped, or raise if it is blank."""
    stripped = value.strip()
    if not stripped:
        raise RenderToPdfValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


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
    pdf_port: ContratosPdfPort,
    *,
    titulo: str = "Contrato",
) -> bytes:
    """Render ``plantilla`` for ``solicitud`` and return PDF bytes.

    The ``titulo`` argument controls the H1 rendered in the PDF. It
    defaults to ``"Contrato"``; callers (CP-3 route handler) override
    it per contract type (``Contrato de Adopción``, etc.).

    The returned bytes are the raw PDF document produced by the port
    and can be passed directly to
    :meth:`ContratosStoragePort.put_pdf` (CP-4).
    """
    _require_non_blank(plantilla.cuerpo, "plantilla.cuerpo")
    _require_non_blank(titulo, "titulo")
    texto = render_contrato(plantilla, solicitud)
    envelope = _wrap_html(texto, titulo=titulo)
    return pdf_port.render_html_to_pdf(envelope)


__all__ = [
    "RenderToPdfValidationError",
    "render_to_pdf",
]
