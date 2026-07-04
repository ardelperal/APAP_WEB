"""Route layer for FOSTER-02 estancias de acogida (CRUD).

Mirrors ``app/modules/foster/routes.py`` (FOSTER-01) and
``app/modules/entradas/routes.py`` (INTAKE-01): routes are pure HTTP /
auth / template glue. All data access delegates to
``app.modules.acogidas.service``.

Endpoints (mounted at ``/acogidas`` by ``app/main.py``):

- ``GET  /acogidas``                       list of stays (active + closed)
                                                with optional ``?activas_solo=1``
                                                filter.
- ``GET  /acogidas/new``                   empty form.
- ``POST /acogidas``                       create; redirect to detail on
                                                success.
- ``GET  /acogidas/{id}``                  detail view with duration +
                                                close/delete buttons.
- ``GET  /acogidas/{id}/edit``             edit form prefilled.
- ``POST /acogidas/{id}/update``           update.
- ``POST /acogidas/{id}/close``            close stay (fecha_final=today).
- ``POST /acogidas/{id}/delete``           soft-delete.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient
from app.modules.acogidas import service as acogidas_service

router = APIRouter(prefix="/acogidas", tags=["foster"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor],
)


_FORM_FIELDS = (
    "animal_id",
    "casa_acogida_id",
    "voluntario_acogida_id",
    "voluntario_seguimiento1_id",
    "voluntario_seguimiento2_id",
    "voluntario_sanitario_id",
    "fecha_inicio",
    "fecha_final",
    "entrada_origen_id",
    "direccion",
    "telefono",
    "observaciones",
)


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    return {key: _opt(form.get(key)) for key in _FORM_FIELDS}


def _acogida_to_form_data(acogida: acogidas_service.Acogida) -> dict[str, Any]:
    return {
        "animal_id": acogida.animal_id,
        "casa_acogida_id": acogida.casa_acogida_id or "",
        "voluntario_acogida_id": acogida.voluntario_acogida_id or "",
        "voluntario_seguimiento1_id": acogida.voluntario_seguimiento1_id or "",
        "voluntario_seguimiento2_id": acogida.voluntario_seguimiento2_id or "",
        "voluntario_sanitario_id": acogida.voluntario_sanitario_id or "",
        "fecha_inicio": acogida.fecha_inicio,
        "fecha_final": acogida.fecha_final or "",
        "entrada_origen_id": acogida.entrada_origen_id or "",
        "direccion": acogida.direccion or "",
        "telefono": acogida.telefono or "",
        "observaciones": acogida.observaciones or "",
    }


def _render_form(
    request: Request,
    user: Any,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "form_action": form_action,
        },
        status_code=status_code,
    )


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_acogidas_view(
    request: Request,
    activas_solo: int | None = None,
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """List stays; ``?activas_solo=1`` filters to open stays."""
    if (early := return_early_if_response(user)) is not None:
        return early
    solo = bool(activas_solo)
    acogidas = acogidas_service.list_acogidas(client, activas_solo=solo)
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/list.html",
        context={
            "user": user,
            "acogidas": acogidas,
            "activas_solo": solo,
        },
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_acogida_form(
    request: Request,
    user: Any = Depends(require_authorized_user),
):
    """Render an empty create form."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/acogidas")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_acogida_view(
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a new estancia; redirect to detail on success, re-render form on validation error."""
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )
    try:
        acogida = acogidas_service.create_acogida(client, form_data)
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            "/acogidas",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/acogidas/{acogida.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{acogida_id}", response_class=HTMLResponse)
def acogida_detail(
    acogida_id: str,
    request: Request,
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the stay detail view with computed duration + active state."""
    if (early := return_early_if_response(user)) is not None:
        return early
    acogida = acogidas_service.get_acogida_by_id(client, acogida_id)
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    duracion = acogidas_service.compute_duracion(acogida)
    active = acogidas_service.is_active(acogida)
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/detail.html",
        context={
            "user": user,
            "acogida": acogida,
            "duracion": duracion,
            "active": active,
        },
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{acogida_id}/edit", response_class=HTMLResponse)
def edit_acogida_form(
    acogida_id: str,
    request: Request,
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the edit form prefilled from the current stay row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    acogida = acogidas_service.get_acogida_by_id(client, acogida_id)
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _acogida_to_form_data(acogida),
        None,
        f"/acogidas/{acogida_id}/update",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{acogida_id}/update", response_class=HTMLResponse)
def update_acogida_view(
    acogida_id: str,
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Apply form edits; redirect to detail on success, re-render on validation error."""
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )
    try:
        acogida = acogidas_service.update_acogida(client, acogida_id, form_data)
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            f"/acogidas/{acogida_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/acogidas/{acogida_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- close (end of stay, lifecycle event) --------------------------------


@router.post("/{acogida_id}/close", response_class=HTMLResponse)
def close_acogida_view(
    acogida_id: str,
    request: Request,
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Close the stay: ``fecha_final = current_date``, ``activo`` stays true.

    D-EST-04: closing is a lifecycle event (the animal returns to the
    shelter or moves to adoption), NOT a soft-delete. The stay row
    remains visible in the listing with ``fecha_final`` populated.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if acogidas_service.close_acogida(client, acogida_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/acogidas/{acogida_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) --------------------------------------------------------


@router.post("/{acogida_id}/delete", response_class=HTMLResponse)
def delete_acogida_view(
    acogida_id: str,
    request: Request,
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete the stay: ``activo = false`` + ``fecha_baja = now()``.

    Redirects to the list view on success. Returns 404 if the service
    reports the row was missing or already inactive.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not acogidas_service.delete_acogida(client, acogida_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/acogidas", status_code=status.HTTP_303_SEE_OTHER
    )
