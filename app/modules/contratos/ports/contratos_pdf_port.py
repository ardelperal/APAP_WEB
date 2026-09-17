"""PDF generator port for the contratos slice (DOC-01 PR 2).

The render-to-pdf use case (``application/render_to_pdf.py``) receives a
:class:`ContratosPdfGeneratorPort` via dependency injection and calls
``render_html_to_pdf`` on it. The concrete adapter under
``adapters/local_backend/`` wraps weasyprint; tests inject a stub that
returns deterministic bytes so the use case stays pure and hermetic.

The Protocol accepts HTML and returns raw PDF bytes. The use case is
responsible for building the HTML wrapper around the rendered contract
text (``application/render_to_pdf.py``) so the generator stays a thin
HTML→PDF converter with no domain knowledge.
"""

from __future__ import annotations

from typing import Protocol


class ContratosPdfGeneratorPort(Protocol):
    """Backend-agnostic PDF generator used by the contratos use case."""

    def render_html_to_pdf(self, html: str) -> bytes:
        """Render ``html`` to PDF and return the raw bytes.

        The adapter must produce a valid PDF document. The use case
        trusts the adapter to handle CSS, fonts, page breaks and any
        library-specific failure mode; the adapter translates transport
        failures into the data-access layer's Protocol exceptions so
        callers stay transport-free.
        """


__all__ = ["ContratosPdfGeneratorPort"]
