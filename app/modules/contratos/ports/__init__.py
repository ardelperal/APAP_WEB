"""Contratos slice — ports layer (DOC-01 CP1, issue #850).

Transport-free surface the application use cases depend on:

- :class:`~app.modules.contratos.ports.contratos_pdf_port.ContratosPdfPort`
  — HTML→PDF generator (reportlab adapter lands in CP3).
- :class:`~app.modules.contratos.ports.contratos_storage_port.ContratosStoragePort`
  — put / get / delete PDF objects (storage adapter lands in CP4).
- :class:`~app.modules.contratos.ports.contrato_pdf.ContratoPdf` —
  value object returned by the storage port.

The slice-completeness gate looks here; no transport import is allowed
in this package (AGENTS.md §33.4).
"""
