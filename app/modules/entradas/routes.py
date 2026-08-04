"""Protected routes for the minimal intake-entry CRUD surface."""

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
from app.core.forms import optional_value as _opt
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.entradas import service as entradas_service
from app.modules.entradas.forms import EntradaForm

router = APIRouter(prefix="/entradas", tags=["entradas"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    return {
        "animal_id": _opt(form.get("animal_id")),
        "voluntario_entrada_id": _opt(form.get("voluntario_entrada_id")),
        "fecha_entrada": _opt(form.get("fecha_entrada")),
        "origen": _opt(form.get("origen")),
        "motivo": _opt(form.get("motivo")),
        "observaciones": _opt(form.get("observaciones")),
    }


def _entrada_to_form_data(entrada: entradas_service.Entrada) -> dict[str, Any]:
    return {
        "animal_id": entrada.animal_id,
        "voluntario_entrada_id": entrada.voluntario_entrada_id or "",
        "fecha_entrada": entrada.fecha_entrada,
        "origen": entrada.origen or "",
        "motivo": entrada.motivo or "",
        "observaciones": entrada.observaciones or "",
    }


def _render_form(  # noqa: PLR0913  # non-route helper; 6 args is minimal for template context
    request: Request,
    user: Response | dict,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    return _templates.TemplateResponse(
        request=request,
        name="entradas/form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "form_action": form_action,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def list_entradas(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    entradas = entradas_service.list_entradas(client)
    return _templates.TemplateResponse(
        request=request,
        name="entradas/list.html",
        context={"user": user, "entradas": entradas},
    )


@router.get("/new", response_class=HTMLResponse)
def new_entrada_form(
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ENTRADAS))],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/entradas")


@router.post("", response_class=HTMLResponse)
def create_entrada_view(
    request: Request,
    form: Annotated[EntradaForm, Form()],
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):  # noqa: PLR0913  # refactored to EntradaForm
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(form.model_dump())
    try:
        entrada = entradas_service.create_entrada(client, form_data)
    except entradas_service.EntradaConflictError:
        return _render_form(
            request,
            user,
            form_data,
            "Ya existe una entrada para ese animal y fecha.",
            "/entradas",
            status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            "/entradas",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/entradas/{entrada.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/{entrada_id}", response_class=HTMLResponse)
def entrada_detail(
    entrada_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    entrada = entradas_service.get_entrada_by_id(client, entrada_id)
    if entrada is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="entradas/detail.html",
        context={"user": user, "entrada": entrada},
    )


@router.get("/{entrada_id}/edit", response_class=HTMLResponse)
def edit_entrada_form(
    entrada_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_permission(Permission.READ_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    entrada = entradas_service.get_entrada_by_id(client, entrada_id)
    if entrada is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _entrada_to_form_data(entrada),
        None,
        f"/entradas/{entrada_id}/update",
    )


@router.post("/{entrada_id}/update", response_class=HTMLResponse)
def update_entrada_view(
    entrada_id: str,
    request: Request,
    form: Annotated[EntradaForm, Form()],
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):  # noqa: PLR0913  # refactored to EntradaForm
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(form.model_dump())
    try:
        entrada = entradas_service.update_entrada(client, entrada_id, form_data)
    except entradas_service.EntradaConflictError:
        return _render_form(
            request,
            user,
            form_data,
            "Ya existe una entrada para ese animal y fecha.",
            f"/entradas/{entrada_id}/update",
            status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            f"/entradas/{entrada_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if entrada is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/entradas/{entrada_id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/{entrada_id}/delete", response_class=HTMLResponse)
def delete_entrada_view(
    entrada_id: str,
    user: Annotated[Response | dict, Depends(require_permission(Permission.WRITE_ENTRADAS))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    if not entradas_service.delete_entrada(client, entrada_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(url="/entradas", status_code=status.HTTP_303_SEE_OTHER)
