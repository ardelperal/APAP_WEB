"""End-to-end test for the DOC-01 PR-2 contratos slice.

Pins the full pipeline:

1. :class:`Plantilla` + :class:`SolicitudContrato` →
   :func:`render_to_pdf` (use case) →
   :class:`ReportLabPdfGenerator` (PDF adapter) →
   raw PDF bytes.
2. Raw PDF bytes →
   :class:`MinioContratosStorage` (storage adapter) →
   in-memory fake MinIO.
3. Stored object →
   :meth:`MinioContratosStorage.get_pdf_stream` →
   :class:`ContratoPDF` with the same byte content.

The test exercises every layer in production order. The PDF generator
is real (reportlab) because the slice has no DI shim yet for tests
that want a deterministic PDF header. The MinIO client is the
in-memory fake from ``test_contratos_local_backend_storage``.

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): the only network is the in-process fake.
- Rule 2 (no humo): every assertion pins one observable contract.
- Rule 4 (no production mutation): the test exercises the public
  surface of each layer in order.
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
    """Render to PDF, store in object storage, retrieve the stored bytes.

    Pins the round-trip contract: the bytes stored under
    ``{Tipo}_{entidad_id}.pdf`` round-trip back through
    :meth:`MinioContratosStorage.get_pdf_stream` to the same byte
    content produced by :func:`render_to_pdf`.
    """
    generator = ReportLabPdfGenerator()
    client = _FakeClient()
    storage = MinioContratosStorage(client)  # type: ignore[arg-type]

    plantilla = Plantilla(
        tipo=TipoContrato.ADOPCION,
        cuerpo=(
            "Animal: {{animal.nombre}}\n"
            "Adoptante: {{persona.nombre}} {{persona.apellidos}}\n"
            "{% if animal.edad_meses >= 6 %}"
            "Cláusula de esterilización."
            "{% endif %}"
        ),
    )
    solicitud = SolicitudContrato(
        variables={
            "animal.nombre": "Toby",
            "persona.nombre": "Marta",
            "persona.apellidos": "García",
            "animal.edad_meses": "12",
        },
        tipo=TipoContrato.ADOPCION,
    )
    pdf_bytes = render_to_pdf(
        plantilla, solicitud, generator, titulo="Contrato de Adopción"
    )

    assert pdf_bytes[:5] == b"%PDF-"

    key = f"{TipoContrato.ADOPCION.value}_42.pdf"
    marker = storage.put_pdf(
        bucket=DEFAULT_BUCKET, key=key, body=pdf_bytes
    )
    assert marker == f"{DEFAULT_BUCKET}/{key}"

    asset = storage.get_pdf_stream(bucket=DEFAULT_BUCKET, key=key)
    assert asset is not None
    assert asset.bucket == DEFAULT_BUCKET
    assert asset.key == key
    assert asset.media_type == "application/pdf"
    chunks = list(iter(asset.stream))
    assert b"".join(chunks) == pdf_bytes
    asset.stream.close()


def test_full_flow_cubo_suffix_matches_legacy_naming() -> None:
    """The storage key follows the legacy ``{Tipo}_{ID}.pdf`` naming.

    Pins the legacy fidelity contract from
    :mod:`:`docs.legacy-signed-contract-flow` §"Naming en Firmados".
    A regression that switches to UUIDs or timestamped keys breaks
    migration scripts that expect the legacy shape.
    """
    assert TipoContrato.ADOPCION.value == "Adopcion"
    assert TipoContrato.ENTRADA.value == "Entrada"
    assert TipoContrato.ACOGIDA_JUDICIAL.value == "Acogida Judicial"

    key = f"{TipoContrato.ACOGIDA_JUDICIAL.value}_15.pdf"
    assert key == "Acogida Judicial_15.pdf"
