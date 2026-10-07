"""Use cases for the contratos slice.

Public surface:

- :func:`render_contrato` — render a ``Plantilla`` against a
  ``SolicitudContrato`` and return the body text (DOC-01 CP-1).
- :func:`render_to_pdf` — render a ``Plantilla`` to PDF bytes via an
  injected :class:`~app.modules.contratos.ports.ContratosPdfPort`
  (DOC-01 CP-2, issue #850); the reportlab adapter lands in CP-3.
- :func:`generate_contrato` — orchestrate the full DOC-01 SLICE-2
  flow: load template, render to PDF, store in object storage and
  persist the ``contratos`` table row (issue #1109, SLICE 2).
"""

from __future__ import annotations

from app.modules.contratos.application.generate_contrato import (
    DEFAULT_BUCKET,
    GeneratedContrato,
    generate_contrato,
)
from app.modules.contratos.application.render_contrato import render_contrato
from app.modules.contratos.application.render_to_pdf import render_to_pdf

__all__ = [
    "DEFAULT_BUCKET",
    "GeneratedContrato",
    "generate_contrato",
    "render_contrato",
    "render_to_pdf",
]
