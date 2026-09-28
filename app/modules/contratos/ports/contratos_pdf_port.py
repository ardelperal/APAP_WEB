"""PDF generator port for the contratos slice (DOC-01 CP1, issue #850).

The render-to-pdf use case (``application/render_to_pdf.py``, CP2)
receives a :class:`ContratosPdfPort` via dependency injection and calls
``render_html_to_pdf`` on it. The concrete adapter under
``adapters/local_backend/`` (CP3) wraps reportlab; tests inject a stub
that returns deterministic bytes so the use case stays pure and
hermetic.

The Protocol accepts an HTML string and returns raw PDF bytes. The use
case is responsible for building the HTML envelope around the rendered
contract text so the generator stays a thin HTML→PDF converter with no
domain knowledge. No transport import is allowed here — the
architectural pin test (``tests/test_slice_contratos_architecture.py``,
AGENTS.md §33.4) enforces this.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ContratosPdfPort(Protocol):
    """Backend-agnostic PDF generator used by the contratos slice."""

    def render_html_to_pdf(self, html: str) -> bytes:
        """Render ``html`` to PDF and return the raw bytes.

        The adapter must produce a valid PDF document. The use case
        trusts the adapter to handle fonts, page breaks and any
        library-specific failure mode; the adapter translates
        transport failures into Protocol-level exceptions so callers
        stay transport-free.
        """


__all__ = ["ContratosPdfPort"]
