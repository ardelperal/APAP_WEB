"""Use case: generate a contract PDF for one entity (DOC-01 SLICE 2, #1109).

Orchestrates the full DOC-01 SLICE-2 flow end-to-end:

1. Validate the contract type against the
   :class:`~app.modules.contratos.domain.tipos_contrato.TipoContrato`
   enum and the entity_type against the four supported FK targets.
2. Load the :class:`~app.modules.contratos.domain.plantilla.Plantilla`
   for the contract type via the injected
   :class:`~app.modules.contratos.ports.contratos_plantilla_port.ContratosPlantillaPort`.
3. Build the variable bundle the template engine needs.
4. Render the template body to PDF bytes via the existing
   :func:`render_to_pdf` use case (CP-2 + CP-3 already merged).
5. Store the PDF bytes in object storage via the
   :class:`~app.modules.contratos.ports.contratos_storage_port.ContratosStoragePort`
   using the legacy ``{Tipo}_{ID}.pdf`` key convention.
6. Persist a ``contratos`` table row via the canonical SQL owner
   (:mod:`app.modules.contratos.contratos_queries`) so the legacy
   uniqueness rule "un único contrato por tipo por entidad" is
   enforced server-side.

The use case is transport-free: every dependency is injected via
the Protocol surfaces (plantilla, PDF, storage) or imported from
the canonical SQL owner (which is a sibling module, not a
transport boundary). The CP-3 route wires the real
:mod:`ReportLabPdfGenerator` and the production
:class:`~app.modules.contratos.adapters.local_backend.contratos_local_backend_storage.MinioContratosStorage`;
tests substitute in-memory fakes.

The :class:`SqlExecutor` is NOT imported here -- the canonical
queries module is the only place the contratos table SQL lives, and
this use case delegates the INSERT to it as a normal function call
(matching how :func:`app.modules.cesiones.application.create_cesion`
delegates to ``CesionesPort``). The application layer stays free
of transport and SQL strings.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.contratos.application.render_to_pdf import render_to_pdf
from app.modules.contratos.contratos_queries import (
    ContratoConflictError,
    ContratoRecord,
    insert_contrato,
)
from app.modules.contratos.domain.plantilla import Plantilla
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort
from app.modules.contratos.ports.contratos_plantilla_port import (
    ContratosPlantillaPort,
)
from app.modules.contratos.ports.contratos_storage_port import (
    ContratosStoragePort,
)

#: Legacy ``TbContratosAnexos`` bucket name. Mirrors
#: ``docs/legacy-signed-contract-flow.md`` §"Naming en Firmados"
#: and :data:`app.modules.contratos.adapters.local_backend
#: .contratos_local_backend_storage.DEFAULT_BUCKET`.
DEFAULT_BUCKET = "apap-contracts"


class ContratoEntityTypeError(ValueError):
    """Raised when ``entity_type`` is not one of the four FK targets.

    Translated to HTTP 422 by the route. Subclasses :class:`ValueError`
    so legacy ``except ValueError`` clauses keep working.
    """


class ContratoTipoInvalidoError(ValueError):
    """Raised when ``tipo`` is not a :class:`TipoContrato` value.

    Translated to HTTP 422 by the route. The use case validates the
    enum up-front so a bad tipo never reaches the storage port.
    """


@dataclass(frozen=True, slots=True)
class GeneratedContrato:
    """The full result of :func:`generate_contrato`.

    ``bucket`` / ``key`` are the object coordinates the storage
    adapter returned; ``pdf_bytes`` is the freshly-rendered body the
    route can stream back to the client.
    """

    record: ContratoRecord
    bucket: str
    key: str
    pdf_bytes: bytes


def _validate_tipo(tipo: str) -> TipoContrato:
    """Return the :class:`TipoContrato` for ``tipo`` or raise.

    Mirrors the legacy ``TbContratosAnexos.TipoContrato`` enum so a
    typo in the form never reaches the catalog lookup. The StrEnum
    constructor raises ``ValueError`` for an unknown value; we wrap
    with a friendlier message.
    """
    try:
        return TipoContrato(tipo)
    except ValueError as exc:
        raise ContratoTipoInvalidoError(  # noqa: TRY003
            f"tipo de contrato invalido: {tipo!r}"
        ) from exc


def _validate_entity_type(entity_type: str) -> str:
    """Return the validated entity type string or raise.

    The four values are the FK targets the contratos table supports;
    :func:`app.modules.contratos.contratos_queries.entity_column`
    raises on anything else, but a clean 422 at the use case is
    friendlier than waiting for the catalog lookup to fail.
    """
    valid = {"entrada", "adopcion", "acogida", "cesion"}
    if entity_type not in valid:
        raise ContratoEntityTypeError(  # noqa: TRY003
            f"entity_type invalido: {entity_type!r} "
            f"(esperado uno de {sorted(valid)})"
        )
    return entity_type


def _build_solicitud(
    *,
    tipo: TipoContrato,
    entity_type: str,
    entity_id: str,
    fecha: str | None,
    extra_variables: dict[str, str],
) -> SolicitudContrato:
    """Compose the variable bundle the template engine needs.

    The eight legacy templates reference ``solicitud.fecha`` plus
    per-template variables (``persona.nombre``, ``animal.nombre``,
    ...). SLICE 2 ships a minimal variable bundle: the entity
    coordinates, the date, and whatever the operator passed in the
    form's ``variables`` JSON field. Future PRs enrich the bundle
    by joining the entity row from the relevant slice.
    """
    variables: dict[str, str] = {
        "solicitud.entity_type": entity_type,
        "solicitud.entity_id": entity_id,
        "solicitud.tipo": tipo.value,
    }
    if fecha:
        variables["solicitud.fecha"] = fecha
    variables.update(extra_variables)
    return SolicitudContrato(variables=variables, tipo=tipo.value)


def _storage_key(tipo: TipoContrato, entity_id: str) -> str:
    """Return the object key for ``(tipo, entity)`` per legacy naming.

    Mirrors :data:`app.modules.contratos.adapters.local_backend
    .contratos_local_backend_storage` and the legacy
    ``TbContratosAnexos.NombreArchivo`` convention documented in
    ``docs/legacy-signed-contract-flow.md`` §5.
    """
    return f"{tipo.value}_{entity_id}.pdf"


def generate_contrato(
    *,
    tipo: str,
    entity_type: str,
    entity_id: str,
    numero_contrato: str,
    fecha: str | None,
    variables: dict[str, str] | None,
    bucket: str,
    plantilla_port: ContratosPlantillaPort,
    pdf_port: ContratosPdfPort,
    storage_port: ContratosStoragePort,
    executor,
) -> GeneratedContrato:
    """Generate the contract PDF, store it and persist the row.

    Parameters
    ----------
    tipo:
        :class:`TipoContrato` value (``"Adopcion"``, ``"Entrada"``,
        ...). Validated up-front against the enum.
    entity_type:
        One of ``"entrada" / "adopcion" / "acogida" / "cesion"``.
    entity_id:
        The primary key of the entity in the respective table.
    numero_contrato:
        Legacy contract number (e.g. ``"CP0672"``). Stored in
        ``contratos.numero_contrato`` and used as the storage key
        prefix.
    fecha:
        Optional contract date (ISO ``YYYY-MM-DD``). When ``None``,
        the row is written with a NULL date (the legacy allows it).
    variables:
        Optional extra template variables (``persona.nombre``,
        ``animal.nombre``, ...). ``None`` is treated as empty.
    bucket:
        Object storage bucket (``DEFAULT_BUCKET`` in production).
    plantilla_port:
        Source of the template body for ``tipo``.
    pdf_port:
        HTML→PDF generator (real reportlab in production, stub in
        tests).
    storage_port:
        Object storage adapter (real MinIO in production, in-memory
        fake in tests).
    executor:
        The :class:`SqlExecutor` Protocol instance. Wired by the
        route's DI from ``request.app.state.sql_executor``. The
        use case passes it through to the canonical queries module
        so the contratos table SQL stays in one place.

    Returns
    -------
    :class:`GeneratedContrato` carrying the persisted record, the
    storage marker and the rendered PDF bytes.

    Raises
    ------
    ContratoTipoInvalidoError:
        ``tipo`` is not a :class:`TipoContrato` value (HTTP 422).
    ContratoEntityTypeError:
        ``entity_type`` is not in the four FK targets (HTTP 422).
    ContratoConflictError:
        another contrato already exists for ``(tipo, entity)``
        (HTTP 409 -- the legacy "un único contrato por tipo por
        entidad" rule, ``docs/legacy-signed-contract-flow.md`` §5).
    """
    tipo_enum = _validate_tipo(tipo)
    entity_type_value = _validate_entity_type(entity_type)
    if not entity_id:
        raise ValueError(  # noqa: TRY003
            "entity_id is required and cannot be empty"
        )
    if not numero_contrato:
        raise ValueError(  # noqa: TRY003
            "numero_contrato is required and cannot be empty"
        )

    # 1. Load the template body for the requested tipo.
    plantilla: Plantilla = plantilla_port.obtener_plantilla(tipo=tipo_enum.value)

    # 2. Build the variable bundle the render engine needs.
    solicitud = _build_solicitud(
        tipo=tipo_enum,
        entity_type=entity_type_value,
        entity_id=entity_id,
        fecha=fecha,
        extra_variables=variables or {},
    )

    # 3. Render the PDF body (CP-2 envelope + CP-3 reportlab).
    titulo = f"Contrato de {tipo_enum.value}"
    pdf_bytes = render_to_pdf(
        plantilla,
        solicitud,
        pdf_port,
        titulo=titulo,
    )

    # 4. Store the PDF in object storage. The legacy key naming is
    #    ``{Tipo}_{ID}.pdf`` per ``docs/legacy-signed-contract-flow.md``
    #    §"Naming en Firmados".
    key = _storage_key(tipo_enum, entity_id)
    storage_port.put_pdf(bucket=bucket, key=key, body=pdf_bytes)

    # 5. Persist the ``contratos`` row via the canonical SQL owner.
    #    The use case delegates the INSERT to the queries module --
    #    the contratos table's sole SQL owner in this slice. The
    #    ``ContratoConflictError`` propagates so the route can
    #    translate it to HTTP 409.
    record = insert_contrato(
        executor,
        tipo=tipo_enum.value,
        entity_type=entity_type_value,
        entity_id=entity_id,
        numero_contrato=numero_contrato,
        fecha=fecha,
    )

    return GeneratedContrato(
        record=record,
        bucket=bucket,
        key=key,
        pdf_bytes=pdf_bytes,
    )


__all__ = [
    "ContratoConflictError",
    "ContratoEntityTypeError",
    "ContratoTipoInvalidoError",
    "DEFAULT_BUCKET",
    "GeneratedContrato",
    "generate_contrato",
    "insert_contrato",
]
