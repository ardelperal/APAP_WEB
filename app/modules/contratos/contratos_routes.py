"""Routes for DOC-01 contract generation and download (issue #1109, SLICE 2).

The slice is a thin HTTP layer over the hexagonal ``app.modules.contratos``
use cases. Auth guards, form parsing, CSRF token checks and PDF
streaming live here; the PDF rendering, template loading, object
storage and SQL INSERTs live behind the application / adapters /
queries layers. AGENTS.md §1 forbids direct SQL in routes; the
canonical contract-side guard is the runtime ``_NoSqlRouteClient``
spy in ``tests/test_contratos_routes.py``.

Endpoints (mounted at ``/contratos`` by ``app/routes_registry.py``):

- ``POST /contratos`` -- generate the contract PDF for one entity
  and persist the ``contratos`` row. Requires
  ``Permission.WRITE_CONTRATOS`` and a valid CSRF token.
  Redirects to the download endpoint on success.
- ``GET  /contratos/{entity_type}/{entity_id}/{tipo}`` -- stream
  the stored PDF for ``(entity_type, entity_id, tipo)``. Requires
  ``Permission.READ_CONTRATOS``. Returns 404 when the contract was
  never generated.

CSRF defense (AGENTS.md rule 10): the form template renders an
``<input type="hidden" name="csrf_token" value="{{ csrf_token }}">``;
``CsrfMiddleware`` validates the token before this handler runs.
The route tests wrap the POST with ``make_csrf_request`` so the
middleware does not reject them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from app.core.auth_dependencies import return_early_if_response
from app.core.rbac import Permission, require_permission
from app.modules.contratos.application.generate_contrato import (
    ContratoConflictError,
    ContratoEntityTypeError,
    ContratoTipoInvalidoError,
    generate_contrato,
)
from app.modules.contratos.contratos_queries import (
    entity_column,
    get_contrato_for_entity,
)
from app.modules.contratos.di import (
    get_contratos_pdf_port,
    get_contratos_plantilla_port,
    get_contratos_sql_executor,
    get_contratos_storage_bucket,
    get_contratos_storage_port,
)
from app.modules.contratos.domain.plantilla import PlantillaNoDisponibleError
from app.modules.contratos.ports.contratos_pdf_port import ContratosPdfPort
from app.modules.contratos.ports.contratos_plantilla_port import (
    ContratosPlantillaPort,
)
from app.modules.contratos.ports.contratos_storage_port import (
    ContratosStoragePort,
)

router = APIRouter(prefix="/contratos", tags=["contratos"])


# ---------------------------------------------------------------------------
# Form binder
# ---------------------------------------------------------------------------


class ContratoForm(BaseModel):
    """Form payload for the ``POST /contratos`` create endpoint."""

    tipo: str
    entity_type: str
    entity_id: str
    numero_contrato: str
    fecha: str | None = None
    variables: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _error_response(message: str, code: int) -> Response:
    """Build the canonical error body for the contratos routes.

    Keeps both handlers under the 50-line budget by sharing the
    single ``Response(...)`` call.
    """
    return Response(content=message, status_code=code)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_class=RedirectResponse)
async def create_contrato(
    form: Annotated[ContratoForm, Form()],
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_CONTRATOS))],
    plantilla_port: Annotated[ContratosPlantillaPort, Depends(get_contratos_plantilla_port)],
    pdf_port: Annotated[ContratosPdfPort, Depends(get_contratos_pdf_port)],
    storage_port: Annotated[ContratosStoragePort, Depends(get_contratos_storage_port)],
    bucket: Annotated[str, Depends(get_contratos_storage_bucket)],
    executor: Annotated[Any, Depends(get_contratos_sql_executor)],
):
    """Generate the contract PDF; redirect to the download on success."""
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        generated = generate_contrato(
            tipo=form.tipo, entity_type=form.entity_type,
            entity_id=form.entity_id, numero_contrato=form.numero_contrato,
            fecha=form.fecha, variables=form.variables, bucket=bucket,
            plantilla_port=plantilla_port, pdf_port=pdf_port,
            storage_port=storage_port, executor=executor,
        )
    except PlantillaNoDisponibleError:
        return _error_response(
            "plantilla no disponible para el tipo solicitado",
            status.HTTP_404_NOT_FOUND,
        )
    except ContratoConflictError:
        return _error_response(
            "ya existe un contrato del mismo tipo para esta entidad",
            status.HTTP_409_CONFLICT,
        )
    except (ContratoTipoInvalidoError, ContratoEntityTypeError, ValueError) as exc:
        return _error_response(
            f"no se pudo generar el contrato: {exc}",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/contratos/{generated.record.entity_type}/"
            f"{generated.record.entity_id}/{generated.record.tipo_codigo}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/{entity_type}/{entity_id}/{tipo}",
    response_class=Response,
)
async def download_contrato(
    entity_type: str,
    entity_id: str,
    tipo: str,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_CONTRATOS))],
    storage_port: Annotated[ContratosStoragePort, Depends(get_contratos_storage_port)],
    bucket: Annotated[str, Depends(get_contratos_storage_bucket)],
    executor: Annotated[Any, Depends(get_contratos_sql_executor)],
):
    """Stream the stored PDF for ``(entity_type, entity_id, tipo)``."""
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        entity_column(entity_type)
    except ValueError:
        return _error_response(
            "entity_type invalido en la URL",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    record = get_contrato_for_entity(
        executor, tipo=tipo, entity_type=entity_type, entity_id=entity_id,
    )
    if record is None:
        return _error_response(
            "no existe un contrato generado para esta entidad y tipo",
            status.HTTP_404_NOT_FOUND,
        )
    asset = storage_port.get_pdf_stream(bucket=bucket, key=f"{tipo}_{entity_id}.pdf")
    if asset is None:
        return _error_response(
            "el PDF del contrato no se encuentra en el almacenamiento",
            status.HTTP_404_NOT_FOUND,
        )
    return Response(
        content=asset.body, media_type=asset.media_type,
        status_code=status.HTTP_200_OK,
    )


__all__ = ["ContratoForm", "router"]
