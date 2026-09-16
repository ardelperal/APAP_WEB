"""Use cases for the contratos slice.

Public surface:

- :func:`render_contrato` — render a ``Plantilla`` against a
  ``SolicitudContrato`` and return the body text. PR 1 of #56 lands
  the engine; PR 3 (later) adds a ``generate_pdf`` use case that
  wraps the renderer with the PDF adapter and the storage adapter.
"""

from __future__ import annotations

from app.modules.contratos.application.render_contrato import render_contrato

__all__ = ["render_contrato"]
