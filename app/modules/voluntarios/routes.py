"""Voluntarios routes: list, create, get, deactivate (soft).

Thin layer on top of ``app.modules.voluntarios.service``. Same pattern
as ``app.modules.animals.routes``: routes handle form parsing,
auth guards, and HTML rendering; the service does the SQL.

Auth: any active user from ``usuarios_autorizados`` (i.e. any
authorized user) can read and create voluntarios. The admin panel
is the only developer-only surface.

Las dependencias de auth (``get_insforge_client_dep``,
``get_current_user_optional`` y ``require_authorized_user``) viven
en ``app.core.auth_dependencies`` para evitar el copy-paste con
``app.modules.animals.routes``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.voluntarios import service as voluntarios_service

router = APIRouter(prefix="/voluntarios", tags=["voluntarios"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    def _opt(key: str) -> str | None:
        value = form.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    return {
        "Voluntario": _opt("Voluntario"),
        "Tel1": _opt("Tel1"),
        "Tel2": _opt("Tel2"),
        "Email": _opt("Email"),
        "DNI": _opt("DNI"),
    }


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_voluntarios_view(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_VOLUNTARIOS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Lista de voluntarios activos, ordenados alfabeticamente."""
    if (early := return_early_if_response(user)) is not None:
        return early
    voluntarios = voluntarios_service.list_voluntarios(client)
    return _templates.TemplateResponse(
        request=request,
        name="voluntarios/list.html",
        context={"user": user, "voluntarios": voluntarios},
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_voluntario_form(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_VOLUNTARIOS))],
):
    """Formulario vacio para dar de alta un voluntario."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="voluntarios/form.html",
        context={
            "user": user,
            "form_data": {},
            "error": None,
        },
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_voluntario_view(  # noqa: PLR0913  # 5 Form fields + 4 fixed deps; form model would reduce by only 4 args
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    Voluntario: Annotated[str, Form()],
    Tel1: Annotated[str | None, Form()] = None,
    Tel2: Annotated[str | None, Form()] = None,
    Email: Annotated[str | None, Form()] = None,
    DNI: Annotated[str | None, Form()] = None,
):
    """Procesa el submit del formulario. En exito, redirect al detalle."""
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params({
        "Voluntario": Voluntario, "Tel1": Tel1, "Tel2": Tel2,
        "Email": Email, "DNI": DNI,
    })

    try:
        voluntario = voluntarios_service.create_voluntario(client, form_data)
    except ValueError as exc:
        return _templates.TemplateResponse(
            request=request,
            name="voluntarios/form.html",
            context={"user": user, "form_data": form_data, "error": str(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        if exc.status_code == 409:
            return _templates.TemplateResponse(
                request=request,
                name="voluntarios/form.html",
                context={
                    "user": user,
                    "form_data": form_data,
                    "error": "Ya existe un voluntario con ese email o DNI. Compruebalo.",
                },
                status_code=status.HTTP_409_CONFLICT,
            )
        raise

    return RedirectResponse(
        url=f"/voluntarios/{voluntario.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{voluntario_id}", response_class=HTMLResponse)
def voluntario_detail(
    voluntario_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_VOLUNTARIOS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Detalle de un voluntario. 404 si no existe."""
    if (early := return_early_if_response(user)) is not None:
        return early
    voluntario = voluntarios_service.get_voluntario_by_id(client, voluntario_id)
    if voluntario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    roles = voluntarios_service.list_roles(client, voluntario_id)
    return _templates.TemplateResponse(
        request=request,
        name="voluntarios/detail.html",
        context={"user": user, "voluntario": voluntario, "roles": roles},
    )


# --- deactivate (soft) ---------------------------------------------------


@router.post("/{voluntario_id}/deactivate", response_class=HTMLResponse)
def deactivate_voluntario_view(
    voluntario_id: str,
    request: Request,  # noqa: ARG001 - FastAPI DI contract
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Soft-delete via un solo ``UPDATE ... WHERE id = $1 AND activo = true``.

    El service hace la SELECT y el UPDATE en una sola sentencia con
    ``RETURNING id``. Asi evitamos el patron anterior (SELECT previo
    + UPDATE) que abria una ventana TOCTOU cuando dos requests
    concurrentes pasaban la guarda de existencia (finding de auditoria
    engram:14518). Patron paralelo: ``app/modules/animals/routes.py::
    delete_animal_view``.

    Devuelve 404 si la fila no existe o ya estaba inactiva
    (``RETURNING id`` vacio -> ``False`` desde el service).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not voluntarios_service.deactivate_voluntario(client, voluntario_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/voluntarios", status_code=status.HTTP_303_SEE_OTHER
    )
