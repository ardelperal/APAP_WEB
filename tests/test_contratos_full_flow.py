"""Full-flow test for the contratos document pipeline (DOC-01, #850).

Pins the production chain in one in-process round trip: Plantilla +
SolicitudContrato → render_to_pdf (CP2) → ReportLabPdfGenerator (CP3,
real reportlab) → MinioContratosStorage (CP4) → in-memory fake S3
client → get_pdf_stream → ContratoPdf, plus the delete leg (retrieve
after delete → None). Real reportlab proves the actual bytes a
contract stores; the fake client keeps it hermetic and unit-level
(apap-testing-strategy §3). web-tdd-philosophy: fixture gate, no humo,
three paths, no production mutation.
"""

from __future__ import annotations

from app.modules.contratos.adapters.local_backend.contratos_local_backend_pdf import (
    ReportLabPdfGenerator,
)
from app.modules.contratos.adapters.local_backend.contratos_local_backend_storage import (
    DEFAULT_BUCKET,
    MinioContratosStorage,
)
from app.modules.contratos.application.render_to_pdf import render_to_pdf
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato
from tests.test_contratos_local_backend_storage import _FakeClient


def test_full_flow_render_store_retrieve_round_trip() -> None:
    """Render, store, retrieve: the bytes come back byte-identical."""
    client = _FakeClient()
    storage = MinioContratosStorage(client)  # type: ignore[arg-type]
    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo="Animal: {{animal.nombre}}\nAdoptante: {{persona.nombre}}",
    )
    solicitud = SolicitudContrato(
        variables={"animal.nombre": "Toby", "persona.nombre": "Marta"},
        tipo=TipoContrato.ADOPCION,
    )
    pdf_bytes = render_to_pdf(
        plantilla,
        solicitud,
        ReportLabPdfGenerator(),
        titulo="Contrato de Adopcion",
    )
    assert pdf_bytes[:5] == b"%PDF-"

    key = f"{TipoContrato.ADOPCION.value}_42.pdf"
    marker = storage.put_pdf(bucket=DEFAULT_BUCKET, key=key, body=pdf_bytes)
    assert marker == f"{DEFAULT_BUCKET}/{key}"

    asset = storage.get_pdf_stream(bucket=DEFAULT_BUCKET, key=key)
    assert asset is not None
    assert asset.bucket == DEFAULT_BUCKET
    assert asset.key == key
    assert asset.media_type == "application/pdf"
    assert asset.body == pdf_bytes
    assert asset.content_length == len(pdf_bytes)


def test_full_flow_delete_then_get_returns_none() -> None:
    """After a successful delete, retrieval returns ``None``."""
    client = _FakeClient()
    storage = MinioContratosStorage(client)  # type: ignore[arg-type]
    key = f"{TipoContrato.ENTRADA.value}_7.pdf"
    storage.put_pdf(bucket=DEFAULT_BUCKET, key=key, body=b"%PDF-fake")

    assert storage.delete_pdf(bucket=DEFAULT_BUCKET, key=key) is True
    assert storage.get_pdf_stream(bucket=DEFAULT_BUCKET, key=key) is None
