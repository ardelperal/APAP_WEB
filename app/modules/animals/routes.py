"""Animals routes: list, create, get, edit, delete (soft).

Thin HTTP layer over the animals slice's hexagonal use cases and port.

Auth model (issue #66 RBAC): permissions are checked via
``require_permission`` from ``app.core.rbac``.  The permission matrix:
- READ_ANIMALES: admin, staff, voluntario
- WRITE_ANIMALES: admin, staff, voluntario
- DELETE_ANIMALES: admin, staff

Las dependencias de auth (``get_local_postgres_executor_dep``,
``get_current_user_optional`` y ``require_permission``) viven
en ``app.core.auth_dependencies`` / ``app.core.rbac`` para evitar
el copy-paste con ``app.modules.voluntarios.routes``.
"""

from __future__ import annotations

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
from starlette.background import BackgroundTask

# Re-export for backwards compat with existing test imports.
# The canonical location is app.core.auth_dependencies.
from app.core.auth_dependencies import (
    get_local_postgres_executor_dep,
    require_authorized_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import SqlExecutor, UniqueViolationError
from app.core.logging import log_safe
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
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
from app.modules.animals.route_helpers import (
    _animal_update_kwargs,
    _chip_change_response,
    _execute_chip_change,
)

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
_require_write_animales = require_permission(Permission.WRITE_ANIMALES)


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
            "form_action": "/animales",
        },
    )


# --- create (submit) ------------------------------------------------------


@router.post("")
def create_animal_view(
    request: Request,
    form: Annotated[AnimalForm, Form()],
    user: Annotated[Response | dict, Depends(_require_write_animales)],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
) -> Response:
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
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
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
            "form_action": f"/animales/{animal_id}/update",
        },
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{animal_id}/update")
def update_animal_view(
    animal_id: str,
    request: Request,
    form: Annotated[AnimalForm, Form()],
    user: Annotated[Response | dict, Depends(_require_write_animales)],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
) -> Response:
    """Procesa el submit de edicion. Redirect al detalle en exito.

    Same ``AnimalForm`` as ``create_animal_view`` — single source of
    truth (see ``app/modules/animals/forms.py``). The handler stays
    thin: it only translates ``ValueError`` -> 422 and success -> 303.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = form.model_dump(exclude_none=True)

    try:
        port.update_animal(animal_id, **_animal_update_kwargs(form_data))
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
    user: Annotated[Response | dict, Depends(_require_write_animales)],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """PATCH /animales/{id}/chip — cambia el chip en cascada a 6 tablas."""
    if (early := return_early_if_response(user)) is not None:
        return early

    result = _execute_chip_change(
        port,
        animal_id,
        payload.new_chip,
        payload.reason,
        user,
    )

    log_safe(
        "animal.chip_changed",
        animal_id=animal_id,
        success=result.success,
        old_chip=result.old_chip,
        new_chip=result.new_chip,
    )

    return _chip_change_response(result)


@router.get("/{animal_id}/foto")
def animal_foto(
    animal_id: str,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ANIMALES))],
    port: Annotated[AnimalsPort, Depends(get_animals_port)],
):
    """Stream a transport-neutral photo asset resolved by ``AnimalsPort``."""
    if (early := return_early_if_response(user)) is not None:
        return early
    photo_asset = port.resolve_animal_photo(animal_id)
    if photo_asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    headers = (
        {"Content-Length": str(photo_asset.content_length)}
        if photo_asset.content_length is not None
        else {}
    )
    return StreamingResponse(
        photo_asset.stream,
        media_type=photo_asset.media_type,
        headers=headers,
        background=BackgroundTask(photo_asset.stream.close),
    )


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
            "form_action": "/animales",
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
