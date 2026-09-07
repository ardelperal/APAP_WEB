"""Voluntarios routes: list, create, get, deactivate (soft), roles.

Thin HTTP layer over the hexagonal use cases and :class:`VoluntariosPort`.
No direct LocalBackend / SQL imports here (AGENTS.md §31).

Auth: any active user from ``usuarios_autorizados`` (i.e. any
authorized user) can read and create voluntarios. The admin panel
is the only developer-only surface.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.core.auth_dependencies import (
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import UniqueViolationError
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.voluntarios.application.assign_voluntario_role import (
    assign_voluntario_role as app_assign_role,
)
from app.modules.voluntarios.application.create_voluntario import (
    create_voluntario as app_create_voluntario,
)
from app.modules.voluntarios.application.deactivate_voluntario import (
    deactivate_voluntario as app_deactivate_voluntario,
)
from app.modules.voluntarios.application.get_voluntario_by_id import (
    get_voluntario_by_id as app_get_voluntario_by_id,
)
from app.modules.voluntarios.application.list_voluntario_roles import (
    list_voluntario_roles as app_list_roles,
)
from app.modules.voluntarios.application.list_voluntarios import (
    list_voluntarios as app_list_voluntarios,
)
from app.modules.voluntarios.application.remove_voluntario_role import (
    remove_voluntario_role as app_remove_role,
)
from app.modules.voluntarios.di import get_voluntarios_port
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort

router = APIRouter(prefix="/voluntarios", tags=["voluntarios"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_Templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_voluntarios_view(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    voluntarios = app_list_voluntarios(port)
    return _Templates.TemplateResponse(
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
    if (early := return_early_if_response(user)) is not None:
        return early
    return _Templates.TemplateResponse(
        request=request,
        name="voluntarios/form.html",
        context={"user": user, "form_data": {}, "error": None},
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_voluntario_view(  # noqa: PLR0913
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
    Voluntario: Annotated[str, Form()],
    Tel1: Annotated[str | None, Form()] = None,
    Tel2: Annotated[str | None, Form()] = None,
    Email: Annotated[str | None, Form()] = None,
    DNI: Annotated[str | None, Form()] = None,
):
    if (early := return_early_if_response(user)) is not None:
        return early

    try:
        voluntario = app_create_voluntario(
            port,
            nombre=Voluntario,
            tel1=Tel1,
            tel2=Tel2,
            email=Email,
            dni=DNI,
        )
    except VoluntarioValidationError as exc:
        return _render_form_error(
            request, user,
            _form_data_from_params(Voluntario, Tel1, Tel2, Email, DNI),
            str(exc),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except UniqueViolationError:
        return _render_form_error(
            request, user,
            _form_data_from_params(Voluntario, Tel1, Tel2, Email, DNI),
            "Ya existe un voluntario con ese email o DNI. Compruebalo.",
            status.HTTP_409_CONFLICT,
        )

    return RedirectResponse(
        url=f"/voluntarios/{voluntario.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{voluntario_id}", response_class=HTMLResponse)
def voluntario_detail(
    voluntario_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    voluntario = app_get_voluntario_by_id(port, voluntario_id)
    if voluntario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    roles = app_list_roles(port, voluntario_id)
    return _Templates.TemplateResponse(
        request=request,
        name="voluntarios/detail.html",
        context={"user": user, "voluntario": voluntario, "roles": roles},
    )


# --- add role -------------------------------------------------------------


@router.post("/{voluntario_id}/roles/add", response_class=HTMLResponse)
def add_voluntario_role(
    voluntario_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
    rol: Annotated[str, Form()],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        app_assign_role(port, voluntario_id=voluntario_id, rol=rol)
    except VoluntarioValidationError as exc:
        return _render_detail_with_error(
            request, user, port, voluntario_id, str(exc)
        )
    except UniqueViolationError:
        return _render_detail_with_error(
            request, user, port, voluntario_id,
            "Este voluntario ya tiene ese rol asignado.",
        )
    return RedirectResponse(
        url=f"/voluntarios/{voluntario_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- remove role -----------------------------------------------------------


@router.post("/{voluntario_id}/roles/remove", response_class=HTMLResponse)
def remove_voluntario_role(
    voluntario_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
    rol: Annotated[str, Form()],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        app_remove_role(port, voluntario_id=voluntario_id, rol=rol)
    except VoluntarioValidationError as exc:
        return _render_detail_with_error(
            request, user, port, voluntario_id, str(exc)
        )
    return RedirectResponse(
        url=f"/voluntarios/{voluntario_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- deactivate (soft) ---------------------------------------------------


@router.post("/{voluntario_id}/deactivate", response_class=HTMLResponse)
def deactivate_voluntario_view(
    voluntario_id: str,
    _request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_VOLUNTARIOS))],
    port: Annotated[VoluntariosPort, Depends(get_voluntarios_port)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    if not app_deactivate_voluntario(port, voluntario_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/voluntarios", status_code=status.HTTP_303_SEE_OTHER
    )


# --- helpers -------------------------------------------------------------


def _form_data_from_params(
    Voluntario: str | None,
    Tel1: str | None,
    Tel2: str | None,
    Email: str | None,
    DNI: str | None,
) -> dict[str, Any]:
    return {
        "Voluntario": Voluntario or "",
        "Tel1": Tel1 or "",
        "Tel2": Tel2 or "",
        "Email": Email or "",
        "DNI": DNI or "",
    }


def _render_form_error(
    request: Request,
    user: Response | dict,
    form_data: dict[str, Any],
    error: str,
    status_code: int,
) -> Response:
    return _Templates.TemplateResponse(
        request=request,
        name="voluntarios/form.html",
        context={"user": user, "form_data": form_data, "error": error},
        status_code=status_code,
    )


def _render_detail_with_error(
    request: Request,
    user: Response | dict,
    port: VoluntariosPort,
    voluntario_id: str,
    error: str,
) -> Response:
    """Re-render detail page with an error message, preserving roles."""
    voluntario = app_get_voluntario_by_id(port, voluntario_id)
    roles = app_list_roles(port, voluntario_id)
    return _Templates.TemplateResponse(
        request=request,
        name="voluntarios/detail.html",
        context={
            "user": user,
            "voluntario": voluntario,
            "roles": roles,
            "role_error": error,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
