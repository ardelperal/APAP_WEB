"""Animals routes: list, create, get, edit, delete (soft).

Transitional thin layer over hexagonal use cases and the legacy
``app.modules.animals.service``. CRUD handlers use ``AnimalsPort``; chip and
photo handlers remain on the service.

Auth model (issue #66 RBAC): permissions are checked via
``require_permission`` from ``app.core.rbac``.  The permission matrix:
- READ_ANIMALES: admin, staff, voluntario
- WRITE_ANIMALES: admin, staff, voluntario
- DELETE_ANIMALES: admin, staff

Las dependencias de auth (``get_insforge_client_dep``,
``get_current_user_optional`` y ``require_permission``) viven
en ``app.core.auth_dependencies`` / ``app.core.rbac`` para evitar
el copy-paste con ``app.modules.voluntarios.routes``.
"""

from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Re-export for backwards compat with existing test imports.
# The canonical location is app.core.auth_dependencies.
from app.core.auth_dependencies import (
    get_insforge_client_dep,
    require_authorized_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import UniqueViolationError
from app.core.insforge import InsForgeClient
from app.core.logging import log_safe
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.animals import photo_service
from app.modules.animals import service as animals_service
from app.modules.animals.application.get_animal_by_id import (
    get_animal_by_id as app_get_animal_by_id,
)
from app.modules.animals.application.list_animals import list_animals as app_list_animals
from app.modules.animals.application.search_animals import (
    search_animals as app_search_animals,
)
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.domain.animal import (
    Animal,
    AnimalSearchResult,
)
from app.modules.animals.domain.animal import (
    Especie as DomainEspecie,
)
from app.modules.animals.domain.animal import (
    Sexo as DomainSexo,
)
from app.modules.animals.forms import AnimalForm
from app.modules.animals.ports.animals_port import AnimalsPort

# Los handlers de create/update reciben los campos ``Especie`` y
# ``Sexo`` del form (mismo nombre que las columnas del schema y los
# enums de dominio). Si importaramos ``Especie`` / ``Sexo`` con su
# nombre canonico, los parametros de los handlers los shadow-ean y
# referencias como ``[e.value for e in EspecieEnum]`` (usadas para
# poblar el dropdown del form en el path 422) iteran sobre los
# caracteres del string en vez de sobre los miembros del enum.
# Por eso importamos los enums bajo alias y usamos los aliases de dominio
# en los bodies de los handlers.
from app.modules.sanidad import get_resumen_sanitario

router = APIRouter(prefix="/animales", tags=["animales"])


# --- chip change payload ------------------------------------------------


class ChipChangePayload(BaseModel):
    """Request body para ``PATCH /animales/{animal_id}/chip``."""

    new_chip: str
    reason: str

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_animales(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """List active animals through the hexagonal port, newest first."""
    if (early := return_early_if_response(user)) is not None:
        return early
    animales = app_list_animals(port)
    return _templates.TemplateResponse(
        request=request,
        name="animales/list.html",
        context={"user": user, "animales": animales},
    )


# --- search (issue #30 LIFECYCLE-05) ---------------------------------------


@router.get("/search", response_class=JSONResponse)
def search_animales(  # noqa: PLR0913  # 9 query filters needed for the search UI; not reducible without removing features
    _request: Request,
    user: Annotated[Response | dict, Depends(require_authorized_user)],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
    q: Annotated[str | None, Query(description="Substring match on nombre (case-insensitive). Ignored if chip is set.")] = None,
    chip: Annotated[str | None, Query(description="Exact match on NCHIP. Takes precedence over q.")] = None,
    especie: Annotated[DomainEspecie | None, Query(description="Exact match: CANINA or FELINA.")] = None,
    sexo: Annotated[DomainSexo | None, Query(description="Exact match: M or H.")] = None,
    estado: Annotated[str | None, Query(description="Dynamic state via animal_current_state JOIN. Values: pendiente_entrada | pendiente_nueva_situacion | albergue | acogida | adoptado | entregado | fallecido | incoherente.")] = None,
    fecha_alta_since: Annotated[str | None, Query(description="ISO date. Filter fecha_alta >= value.")] = None,
    fecha_alta_until: Annotated[str | None, Query(description="ISO date. Filter fecha_alta <= value.")] = None,
    limit: Annotated[int, Query(ge=0, le=200, description="Results per page. Default 50, max 200. 0 returns only total (count-only).")] = 50,
    offset: Annotated[int, Query(ge=0, description="Pagination cursor.")] = 0,
):
    """Search animals with multi-field filters (issue #30 LIFECYCLE-05).

    Returns JSON: ``{"data": [...], "total": N, "limit": N, "offset": N}``.
    Protected with ``require_authorized_user`` (any authenticated user).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    result = app_search_animals(
        port,
        q=q,
        chip=chip,
        especie=especie,
        sexo=sexo,
        estado=estado,
        fecha_alta_since=fecha_alta_since,
        fecha_alta_until=fecha_alta_until,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(content=_search_result_to_json(result))


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_animal_form(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
):
    """Formulario vacio para dar de alta un animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": {},
            "error": None,
            "especies": [e.value for e in DomainEspecie],
            "sexos": [s.value for s in DomainSexo],
        },
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_animal_view(
    request: Request,
    form: Annotated[AnimalForm, Form()],
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Procesa el submit del formulario. En exito, redirect al detalle.

    Uses ``AnimalForm`` (Pydantic v2 with ``Form()``) as the single
    source of truth for the 24 form fields. Adding a column means
    adding it to ``app.modules.animals.forms.AnimalForm`` (which
    asserts the field set matches the service's ``_INSERT_COLUMNS``
    at import time) — the two routes cannot drift.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = form.model_dump(exclude_none=True)
    optional_fields = {
        key: value
        for key, value in form_data.items()
        if key not in {"NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento"}
    }

    try:
        animal = port.create_animal(
            nchip=form_data["NCHIP"],
            nombre=form_data["NombreAnimal"],
            especie=DomainEspecie(form_data["Especie"]),
            sexo=DomainSexo(form_data["Sexo"]),
            fnacimiento=form_data["FNacimiento"],
            **optional_fields,
        )
    except ValueError as exc:
        return _render_animal_form_error(
            request, user, form_data, str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    except UniqueViolationError:
        return _render_animal_form_error(
            request,
            user,
            form_data,
            "Ya existe un animal con ese NCHIP. Compruebalo.",
            status.HTTP_409_CONFLICT,
        )

    return RedirectResponse(
        url=f"/animales/{animal.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{animal_id}", response_class=HTMLResponse)
def animal_detail(
    animal_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Detalle de un animal. 404 si no existe."""
    if (early := return_early_if_response(user)) is not None:
        return early
    animal = app_get_animal_by_id(port, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="animales/detail.html",
        context={"user": user, "animal": animal},
    )


# --- HEALTH-03 salud resumen (issue #52) -----------------------------------


@router.get("/{animal_id}/salud/resumen", response_class=JSONResponse)
def animal_salud_resumen(
    animal_id: str,
    user: Annotated[Response | dict, Depends(require_authorized_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Health summary: latest actuacion per tipo for one animal.

    GET /animales/{animal_id}/salud/resumen
    Returns the most recent ``actuacion_sanitaria`` row per
    ``catalogos_pruebas.observaciones`` (tipo), with fecha, resultado,
    descripcion, and producto.

    Protected with ``require_authorized_user`` per spec acceptance criteria.
    Returns an empty resumen list when no actuaciones exist for the animal.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    resumen = get_resumen_sanitario(client, animal_id)
    return JSONResponse(content={
        "animal_id": resumen.animal_id,
        "nchip": resumen.nchip or "",
        "resumen": [
            {
                "tipo": item.tipo,
                "ultima_fecha": item.ultima_fecha,
                "ultimo_resultado": item.ultimo_resultado or "",
                "ultima_descripcion": item.ultima_descripcion or "",
                "producto": item.producto,
            }
            for item in resumen.resumen
        ],
    })


# --- edit (form prellenado) ----------------------------------------------


@router.get("/{animal_id}/edit", response_class=HTMLResponse)
def edit_animal_form(
    animal_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Formulario prellenado para editar un animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
    animal = app_get_animal_by_id(port, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": _animal_to_form_data(animal),
            "error": None,
            "especies": [e.value for e in DomainEspecie],
            "sexos": [s.value for s in DomainSexo],
        },
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{animal_id}/update", response_class=HTMLResponse)
def update_animal_view(
    animal_id: str,
    request: Request,
    form: Annotated[AnimalForm, Form()],
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Procesa el submit de edicion. Redirect al detalle en exito.

    Same ``AnimalForm`` as ``create_animal_view`` — single source of
    truth (see ``app/modules/animals/forms.py``). The handler stays
    thin: it only translates ``ValueError`` -> 422 and success -> 303.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = form.model_dump(exclude_none=True)
    optional_fields = {
        key: value
        for key, value in form_data.items()
        if key not in {"NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento"}
    }

    try:
        port.update_animal(
            animal_id,
            nombre=form_data.get("NombreAnimal"),
            especie=(
                DomainEspecie(form_data["Especie"])
                if "Especie" in form_data else None
            ),
            sexo=DomainSexo(form_data["Sexo"]) if "Sexo" in form_data else None,
            fnacimiento=form_data.get("FNacimiento"),
            **optional_fields,
        )
    except ValueError as exc:
        return _render_animal_form_error(
            request, user, form_data, str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT
        )

    return RedirectResponse(
        url=f"/animales/{animal_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) -------------------------------------------------------


@router.post("/{animal_id}/delete", response_class=HTMLResponse)
def delete_animal_view(
    animal_id: str,
    _request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.DELETE_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Soft-delete through ``AnimalsPort`` and redirect to the list."""
    if (early := return_early_if_response(user)) is not None:
        return early
    if port.delete_animal(animal_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/animales", status_code=status.HTTP_303_SEE_OTHER
    )


# --- chip change (issue #29, LIFECYCLE-04) -------------------------------


@router.patch("/{animal_id}/chip", response_model=dict[str, Any])
def change_chip_view(
    animal_id: str,
    payload: ChipChangePayload,
    user: Annotated[Response | dict, Depends(require_authorized_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """PATCH /animales/{id}/chip — cambia el chip en cascada a 6 tablas."""
    if (early := return_early_if_response(user)) is not None:
        return early

    user_id = user.get("user_id", "") if isinstance(user, dict) else ""
    animal = animals_service.get_animal_by_id(client, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    result = animals_service.change_animal_chip(
        client,
        animal_id=animal_id,
        old_chip=animal.NCHIP,
        new_chip=payload.new_chip,
        reason=payload.reason,
        operador_user_id=user_id,
    )

    log_safe(
        "animal.chip_changed",
        animal_id=animal_id,
        success=result.success,
        old_chip=result.old_chip,
        new_chip=result.new_chip,
    )

    if not result.success:
        if "ya esta asignado" in (result.error or ""):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.error)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result.error)

    return {
        "success": True,
        "old_chip": result.old_chip,
        "new_chip": result.new_chip,
        "updated_tables": result.updated_tables,
    }


@router.get("/{animal_id}/foto")
def animal_foto(
    animal_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    outcome = photo_service.resolve_animal_photo(client, animal_id)
    if outcome is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if outcome.status == "not_found":
        return StreamingResponse(outcome.stream, media_type=outcome.content_type, headers={
            "ETag": outcome.etag, "Cache-Control": outcome.cache_control,
            **({"Content-Length": str(outcome.content_length)} if outcome.content_length else {}),
        })
    if request.headers.get("if-none-match") == outcome.etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={
            "ETag": outcome.etag, "Cache-Control": outcome.cache_control})
    try:
        first_chunk = next(outcome.stream)
    except StopIteration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except Exception as exc:
        log_safe("animals.photo.stream_error", animal_id=animal_id, error=type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    return StreamingResponse(chain([first_chunk], outcome.stream), media_type=outcome.content_type, headers={
        "ETag": outcome.etag, "Cache-Control": outcome.cache_control,
        **({"Content-Length": str(outcome.content_length)} if outcome.content_length else {}),
    })


# --- helpers -------------------------------------------------------------
def _render_animal_form_error(
    request: Request,
    user: Response | dict,
    form_data: dict[str, Any],
    error: str,
    status_code: int,
) -> Response:
    """Render the shared animal form error response."""
    return _templates.TemplateResponse(
        request=request,
        name="animales/form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "especies": [item.value for item in DomainEspecie],
            "sexos": [item.value for item in DomainSexo],
        },
        status_code=status_code,
    )


def _search_result_to_json(result: AnimalSearchResult) -> dict[str, Any]:
    """Map ``AnimalSearchResult`` to the spec JSON envelope."""
    return {
        "data": [
            {
                "id": a.id,
                "chip": a.NCHIP,
                "nombre": a.NombreAnimal,
                "especie": a.Especie.value,
                "sexo": a.Sexo.value,
                "estado": a.estado,
                "fecha_nacimiento": a.FNacimiento,
                "fecha_alta": a.fecha_alta,
            }
            for a in result.data
        ],
        "total": result.total,
        "limit": result.limit,
        "offset": result.offset,
    }


def _animal_to_form_data(animal: Animal) -> dict[str, Any]:
    """Convierte un Animal a dict para pre-rellenar el form."""
    return {
        "NCHIP": animal.NCHIP or "",
        "NombreAnimal": animal.NombreAnimal or "",
        "Especie": animal.Especie.value if animal.Especie else "",
        "Sexo": animal.Sexo.value if animal.Sexo else "",
        "FNacimiento": animal.FNacimiento or "",
        "TraeNChip": animal.TraeNChip or "",
        "FIMPLANTACIONCHIP": animal.FIMPLANTACIONCHIP or "",
        "Raza": animal.Raza or "",
        "Color": animal.Color or "",
        "Pelo": animal.Pelo or "",
        "Tamano": animal.Tamano or "",
        "Caracter": animal.Caracter or "",
        "FDefuncion": animal.FDefuncion or "",
        "Terapia": animal.Terapia or "",
        "Observaciones": animal.Observaciones or "",
        "NombreFoto": animal.NombreFoto or "",
        "Cartilla": animal.Cartilla or "",
        "Eutanasia": animal.Eutanasia or "",
        "RazaPPP": animal.RazaPPP or "",
        "Mestizo": animal.Mestizo or "",
        "EutanasiaOtrasCausas": animal.EutanasiaOtrasCausas or "",
        "EutanasiaEnfermedad": animal.EutanasiaEnfermedad or "",
        "UltimoEstadoAntesDeFallecido": animal.UltimoEstadoAntesDeFallecido or "",
        "ComunicacionARIAC": animal.ComunicacionARIAC or "",
    }
