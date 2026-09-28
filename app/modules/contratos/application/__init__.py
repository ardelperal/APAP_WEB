"""Use cases for the contratos slice.

Public surface:

- :func:`render_contrato` — render a ``Plantilla`` against a
  ``SolicitudContrato`` and return the body text (DOC-01 CP-1).
- :func:`render_to_pdf` — render a ``Plantilla`` to PDF bytes via an
  injected :class:`~app.modules.contratos.ports.ContratosPdfPort`
  (DOC-01 CP-2, issue #850); the reportlab adapter lands in CP-3.
"""

from __future__ import annotations

from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.application.render_to_pdf import render_to_pdf

__all__ = ["render_contrato", "render_to_pdf"]
