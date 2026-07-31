"""Route layer for FOSTER-01 casas de acogida (CRUD).

Mirrors ``app/modules/voluntarios/routes.py`` and
``app/modules/entradas/routes.py``: routes are pure HTTP / auth /
template glue. All data access delegates to
``app.modules.foster.service``.

Endpoints (mounted at ``/casas-acogida`` by ``app/main.py``):

- ``GET  /casas-acogida``                       list of active houses
                                                (with optional
                                                ``?especie=`` filter).
- ``GET  /casas-acogida/new``                  empty form.
- ``POST /casas-acogida``                       create; redirect to
                                                detail on success.
- ``GET  /casas-acogida/{id}``                 detail view.
- ``GET  /casas-acogida/{id}/edit``            edit form prefilled.
- ``POST /casas-acogida/{id}/update``          update.
- ``POST /casas-acogida/{id}/delete``          soft-delete.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import Rol
from app.core.auth_dependencies import (
    AuthenticatedUser,
    get_insforge_client_dep,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.forms import optional_value as _opt
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.foster import assignment as foster_assignment_service
from app.modules.foster import service as foster_service
from app.modules.foster.forms import (
    CASA_ACOGIDA_FORM_FIELDS,
    CasaAcogidaForm,
)

router = APIRouter(prefix="/casas-acogida", tags=["foster"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


_FORM_FIELDS_STR: tuple[str, ...] = tuple(
    name for name in CASA_ACOGIDA_FORM_FIELDS if name != "capacidad"
)
# ``capacidad`` is parsed as ``int`` by the Pydantic ``CasaAcogidaForm``
# (Form(...) with int type coerces form-encoded strings). The previous
# silent try/except on ``int(capacidad_raw)`` (#140 W2) is gone — bad
# input now surfaces as a FastAPI 422 from Pydantic at parse time
# instead of being silently passed through and re-rejected by the
# service with the same Spanish message (which is what the silent
# except did, just with two failure modes).


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Map a CasaAcogidaForm dump to the dict shape service expects.

    String fields are trimmed; empty strings become ``None`` so the
    service stores NULL. ``capacidad`` arrives as ``int`` from
    Pydantic and passes through unchanged — its bounds check lives in
    the service ``_validate_capacidad`` so the friendly Spanish error
    message stays in one place.
    """
    params: dict[str, Any] = {
        key: _opt(form.get(key)) for key in _FORM_FIELDS_STR
    }
    params["capacidad"] = form.get("capacidad")
    return params


def _casa_to_form_data(casa: foster_service.CasaAcogida) -> dict[str, Any]:
    return {
        "nombre": casa.nombre,
        "apellidos": casa.apellidos,
        "dni_acogedor": casa.dni_acogedor or "",
        "calle": casa.calle,
        "numero": casa.numero or "",
        "piso": casa.piso or "",
        "letra": casa.letra or "",
        "localidad": casa.localidad or "",
        "provincia": casa.provincia or "",
        "cp": casa.cp or "",
        "telefono": casa.telefono,
        "telefono2": casa.telefono2 or "",
        "email": casa.email or "",
        "vinculacion": casa.vinculacion or "",
        "caracteristicas": casa.caracteristicas or "",
        "coche": casa.coche,
        "especie_preferente": casa.especie_preferente or "",
        "observaciones": casa.observaciones or "",
        "capacidad": casa.capacidad,
    }


def _render_form(
    request: Request,
    user: AuthenticatedUser,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    return _templates.TemplateResponse(
        request=request,
        name="casas_acogida/form.html",
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
def list_casas_acogida_view(
    request: Request,
    especie: str | None = None,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    if (early := return_early_if_response(user)) is not None:
        return early
    casas = foster_service.list_casas_acogida(client, especie=especie)
    return _templates.TemplateResponse(
        request=request,
        name="casas_acogida/list.html",
        context={"user": user, "casas": casas, "especie": especie or ""},
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_casa_acogida_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_CASAS_ACOGIDA)),
):
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/casas-acogida")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_casa_acogida_view(
    request: Request,
    form: CasaAcogidaForm = Form(...),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Procesa el submit del formulario. En exito, redirect al detalle.

    Uses ``CasaAcogidaForm`` (Pydantic v2 with ``Form()``) as the
    single source of truth for the 19 form fields. Adding a column
    means adding it to ``app.modules.foster.forms.CasaAcogidaForm``
    (which asserts the field set is a subset of the service's
    ``_WRITE_COLUMNS`` at import time) — the two routes cannot drift.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(
        form.model_dump(exclude_none=True)
    )
    try:
        casa = foster_service.create_casa_acogida(client, form_data)
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            "/casas-acogida",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/casas-acogida/{casa.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{casa_id}", response_class=HTMLResponse)
def casa_acogida_detail(
    casa_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    if (early := return_early_if_response(user)) is not None:
        return early
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # FOSTER-03 (#45): the detail view shows two more pieces of state:
    # the count of active stays (used for the "Estancias activas" badge
    # in the header) and the most recent capacity overrides (top 10).
    # Both are looked up via the assignment service so the route stays
    # SQL-free — the service owns the queries.
    estancias_activas = foster_assignment_service.count_active_estancias_for_casa(
        client, casa_id
    )
    # FOSTER-03 (#45) P1 risk-review fix: the override historial carries
    # ``motivo`` (free text from the operator, potential PII). Only inject
    # it into the template context when the current user is a developer.
    # For non-developers, the template's ``{% if user.rol == "developer" %}``
    # block is skipped automatically (Python falsy -> Jinja skip), and the
    # underlying SQL query never runs because we short-circuit before
    # calling ``list_overrides_for_casa``. The template guard is defense
    # in depth (the source-of-truth guard is here, in the route).
    context: dict[str, Any] = {
        "user": user,
        "casa": casa,
        "estancias_activas": estancias_activas,
    }
    if isinstance(user, dict) and user.get("rol") == Rol.DEVELOPER.value:
        overrides = foster_assignment_service.list_overrides_for_casa(client, casa_id)
        context["overrides"] = overrides[:10]
    return _templates.TemplateResponse(
        request=request,
        name="casas_acogida/detail.html",
        context=context,
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{casa_id}/edit", response_class=HTMLResponse)
def edit_casa_acogida_form(
    casa_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    if (early := return_early_if_response(user)) is not None:
        return early
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _casa_to_form_data(casa),
        None,
        f"/casas-acogida/{casa_id}/update",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{casa_id}/update", response_class=HTMLResponse)
def update_casa_acogida_view(
    casa_id: str,
    request: Request,
    form: CasaAcogidaForm = Form(...),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Procesa el submit del formulario de edicion. En exito, redirect al detalle.

    Same Pydantic form as ``create_casa_acogida_view`` — single source
    of truth in ``app.modules.foster.forms.CasaAcogidaForm``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(
        form.model_dump(exclude_none=True)
    )
    try:
        casa = foster_service.update_casa_acogida(client, casa_id, form_data)
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            f"/casas-acogida/{casa_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/casas-acogida/{casa_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) --------------------------------------------------------


@router.post("/{casa_id}/delete", response_class=HTMLResponse)
def delete_casa_acogida_view(
    casa_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_CASAS_ACOGIDA)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    if (early := return_early_if_response(user)) is not None:
        return early
    if not foster_service.delete_casa_acogida(client, casa_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/casas-acogida", status_code=status.HTTP_303_SEE_OTHER
    )
