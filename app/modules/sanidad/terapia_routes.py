"""Route layer for HEALTH-05 terapias + recomendaciones (issue #54).

Mirrors ``app/modules/sanidad/routes.py`` style: routes are pure
HTTP / auth / template glue. All data access delegates to
``app.modules.sanidad.terapia_service``.

Endpoints (mounted at ``/terapias``):

Terapias:
- ``GET  /terapias``                    list (optional ``?animal_id=`` filter)
- ``GET  /terapias/new``               empty create form
- ``POST /terapias``                    create; redirect to detail on success
- ``GET  /terapias/{terapia_id}``      detail view (includes recomendaciones)
- ``GET  /terapias/{terapia_id}/edit``  edit form
- ``POST /terapias/{terapia_id}/update`` update
- ``POST /terapias/{terapia_id}/delete`` soft-delete (409 if pending recommendations)

Recomendaciones:
- ``POST /terapias/{terapia_id}/recomendaciones``   create linked to terapia
- ``POST /recomendaciones/{id}/complete``            mark completada=true
- ``POST /recomendaciones/{id}/delete``             soft-delete

Auth: all write endpoints require ``WRITE_SALUD``; read endpoints require
``READ_SALUD``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    AuthenticatedUser,
    get_insforge_client_dep,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.forms import optional_value as _opt
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.logging import log_safe
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.sanidad import terapia_service as terapia_service

router = APIRouter(tags=["sanidad-terapias"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
    ],
)


# --- helpers --------------------------------------------------------------


def _terapia_to_form_data(terapia: terapia_service.Terapia) -> dict[str, Any]:
    return {
        "animal_id": terapia.animal_id,
        "voluntario_id": terapia.voluntario_id or "",
        "fecha": terapia.fecha,
        "descripcion": terapia.descripcion or "",
    }


def _clean_terapia_params(
    animal_id: str,
    voluntario_id: str,
    fecha: str,
    descripcion: str | None,
) -> dict[str, Any]:
    """Map raw form fields to the service-param shape."""
    return {
        "animal_id": _opt(animal_id),
        "voluntario_id": _opt(voluntario_id),
        "fecha": _opt(fecha),
        "descripcion": _opt(descripcion),
    }


def _render_terapia_form(
    request: Request,
    user: AuthenticatedUser,
    form_data: dict[str, Any],
    form_action: str,
    is_edit: bool,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    """Render ``sanidad/terapia_form.html`` with the given context."""
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/terapia_form.html",
        context={
            "user": user,
            "form_data": form_data,
            "form_action": form_action,
            "is_edit": is_edit,
            "error": error,
        },
        status_code=status_code,
    )


def _actor_user_id(user: AuthenticatedUser) -> str | None:
    if isinstance(user, dict):
        uid = user.get("user_id")
        return str(uid) if uid is not None else None
    return None


# --- terapia routes ------------------------------------------------------


@router.get("/terapias", response_class=HTMLResponse)
def list_terapias_view(
    request: Request,
    animal_id: str | None = None,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """List active ``terapias``; ``?animal_id=`` filters to one animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
    animal_id = (animal_id or "").strip() or None
    if animal_id:
        terapias = terapia_service.list_terapias(client, animal_id=animal_id)
    else:
        terapias = terapia_service.list_terapias(client)
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/terapias_list.html",
        context={
            "user": user,
            "terapias": terapias,
            "animal_id": animal_id or "",
        },
    )


@router.get("/terapias/new", response_class=HTMLResponse)
def new_terapia_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_SALUD)),
):
    """Render empty create form for a new terapia."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/terapia_form.html",
        context={
            "user": user,
            "form_data": {},
            "error": None,
            "form_action": "/terapias",
            "is_edit": False,
        },
    )


@router.post("/terapias", response_class=HTMLResponse)
def create_terapia_view(
    request: Request,
    animal_id: str = Form(...),
    voluntario_id: str = Form(...),
    fecha: str = Form(...),
    descripcion: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a new terapia; redirect to detail on success."""
    if (early := return_early_if_response(user)) is not None:
        return early
    params = _clean_terapia_params(animal_id, voluntario_id, fecha, descripcion)
    try:
        terapia = terapia_service.create_terapia(
            client, params, actor_user_id=_actor_user_id(user)
        )
    except ValueError as exc:
        return _render_terapia_form(
            request=request,
            user=user,
            form_data=params,
            form_action="/terapias",
            is_edit=False,
            error=f"No se pudo guardar la terapia: {exc}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        log_safe(
            "therapy.create.backend_error",
            status_code=exc.status_code,
        )
        return _render_terapia_form(
            request=request,
            user=user,
            form_data=params,
            form_action="/terapias",
            is_edit=False,
            error="No se pudo contactar con el backend. Inténtalo de nuevo.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return RedirectResponse(
        url=f"/terapias/{terapia.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/terapias/{terapia_id}", response_class=HTMLResponse)
def terapia_detail(
    terapia_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Detail view with recomendaciones listed."""
    if (early := return_early_if_response(user)) is not None:
        return early
    terapia = terapia_service.get_terapia(client, terapia_id)
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    recomendaciones = terapia_service.list_recomendaciones(client, terapia_id)
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/terapia_detail.html",
        context={
            "user": user,
            "terapia": terapia,
            "recomendaciones": recomendaciones,
        },
    )


@router.get("/terapias/{terapia_id}/edit", response_class=HTMLResponse)
def edit_terapia_form(
    terapia_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Edit form prefilled from the persisted row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    terapia = terapia_service.get_terapia(client, terapia_id)
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/terapia_form.html",
        context={
            "user": user,
            "form_data": _terapia_to_form_data(terapia),
            "error": None,
            "form_action": f"/terapias/{terapia_id}/update",
            "is_edit": True,
        },
    )


@router.post("/terapias/{terapia_id}/update", response_class=HTMLResponse)
def update_terapia_view(
    terapia_id: str,
    request: Request,
    animal_id: str = Form(...),
    voluntario_id: str = Form(...),
    fecha: str = Form(...),
    descripcion: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Update an existing terapia; redirect to detail on success."""
    if (early := return_early_if_response(user)) is not None:
        return early
    params = _clean_terapia_params(animal_id, voluntario_id, fecha, descripcion)
    try:
        updated = terapia_service.update_terapia(
            client, terapia_id, params, actor_user_id=_actor_user_id(user)
        )
    except ValueError as exc:
        return _render_terapia_form(
            request=request,
            user=user,
            form_data=params,
            form_action=f"/terapias/{terapia_id}/update",
            is_edit=True,
            error=f"No se pudo guardar la terapia: {exc}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        log_safe("therapy.update.backend_error", status_code=exc.status_code)
        return _render_terapia_form(
            request=request,
            user=user,
            form_data=params,
            form_action=f"/terapias/{terapia_id}/update",
            is_edit=True,
            error="No se pudo contactar con el backend. Inténtalo de nuevo.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/terapias/{updated.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/terapias/{terapia_id}/delete", response_class=HTMLResponse)
def delete_terapia_view(
    terapia_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete a terapia (409 if pending recomendaciones)."""
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        deleted = terapia_service.delete_terapia(
            client, terapia_id, actor_user_id=_actor_user_id(user)
        )
    except terapia_service.TerapiaDeleteError as exc:
        terapia = terapia_service.get_terapia(client, terapia_id)
        recomendaciones = []
        if terapia:
            recomendaciones = terapia_service.list_recomendaciones(client, terapia_id)
        return _templates.TemplateResponse(
            request=request,
            name="sanidad/terapia_detail.html",
            context={
                "user": user,
                "terapia": terapia,
                "recomendaciones": recomendaciones,
                "delete_error": str(exc),
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    except InsForgeError as exc:
        log_safe("therapy.delete.backend_error", status_code=exc.status_code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/terapias", status_code=status.HTTP_303_SEE_OTHER
    )


# --- recomendacion routes -------------------------------------------------


@router.post("/terapias/{terapia_id}/recomendaciones",
             response_class=HTMLResponse)
def create_recomendacion_view(
    terapia_id: str,
    request: Request,
    fecha: str = Form(...),
    texto: str = Form(...),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a recomendacion linked to a terapia; redirect to detail."""
    if (early := return_early_if_response(user)) is not None:
        return early
    params = {"fecha": _opt(fecha), "texto": _opt(texto)}
    try:
        terapia_service.create_recomendacion(
            client, terapia_id, params, actor_user_id=_actor_user_id(user)
        )
    except ValueError as exc:
        # Redirect to terapia detail with error in query param
        return RedirectResponse(
            url=f"/terapias/{terapia_id}?error={str(exc)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except InsForgeError as exc:
        log_safe(
            "recomendacion.create.backend_error",
            terapia_id=terapia_id,
            status_code=exc.status_code,
        )
        return RedirectResponse(
            url=f"/terapias/{terapia_id}?error=backend",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        url=f"/terapias/{terapia_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/recomendaciones/{recomendacion_id}/complete",
             response_class=HTMLResponse)
def complete_recomendacion_view(
    recomendacion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Mark a recomendacion as completed; redirect back to terapia detail."""
    if (early := return_early_if_response(user)) is not None:
        return early
    # Look up the terapia_id for redirect before we call complete
    terapia_id: str | None = None
    try:
        terapia_id = terapia_service.get_recomendacion_terapia_id(
            client, recomendacion_id
        )
    except Exception:
        pass

    try:
        result = terapia_service.complete_recomendacion(
            client, recomendacion_id, actor_user_id=_actor_user_id(user)
        )
    except ValueError:
        terapia_id_str = terapia_id or ""
        return RedirectResponse(
            url=f"/terapias/{terapia_id_str}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except InsForgeError as exc:
        log_safe(
            "recomendacion.complete.backend_error",
            recomendacion_id=recomendacion_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    redirect_id = terapia_id or (result.terapia_id if result else "")
    return RedirectResponse(
        url=f"/terapias/{redirect_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/recomendaciones/{recomendacion_id}/delete",
             response_class=HTMLResponse)
def delete_recomendacion_view(
    recomendacion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_SALUD)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete a recomendacion; redirect back to terapia detail."""
    if (early := return_early_if_response(user)) is not None:
        return early
    # Look up terapia_id for redirect
    terapia_id: str | None = None
    try:
        terapia_id = terapia_service.get_recomendacion_terapia_id(
            client, recomendacion_id
        )
    except Exception:
        pass

    deleted = terapia_service.delete_recomendacion(
        client, recomendacion_id, actor_user_id=_actor_user_id(user)
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/terapias/{terapia_id or ''}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
