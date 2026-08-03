"""Route layer for HEALTH-04 salud (terapias + recomendaciones CRUD).

Mirrors ``app/modules/sanidad/routes.py``: routes are pure HTTP / auth /
template glue. All data access delegates to ``app.modules.salud.service``.

Endpoints (mounted at ``/terapias`` and ``/recomendaciones``):

- ``GET  /terapias``                    list (with optional ``?animal_id=`` filter)
- ``POST /terapias``                    create; redirect to detail on success.
                                          **Requires writer rol.**
- ``GET  /terapias/{id}``              detail view (with recomendaciones).
- ``GET  /terapias/{id}/edit``         edit form prefilled.
- ``POST /terapias/{id}/update``       update. **Requires writer rol.**
- ``POST /terapias/{id}/delete``       soft-delete (409 if pending recommendations).
                                          **Requires writer rol.**
- ``GET  /terapias/{terapia_id}/recomendaciones``   list recomendaciones.
- ``POST /terapias/{terapia_id}/recomendaciones``   create.
                                          **Requires writer rol.**
- ``PATCH  /recomendaciones/{id}``      mark as completed (completada=true).
                                          **Requires writer rol.**
- ``DELETE /recomendaciones/{id}``      soft-delete. **Requires writer rol.**

Auth model (issue #144): GET endpoints use ``require_permission(Permission.READ_SALUD)``.
Write endpoints use ``require_permission(Permission.WRITE_SALUD)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

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
from app.modules.salud import service as salud_service

router = APIRouter(tags=["salud"])

_HPROXIES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(
    directory=_HPROXIES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
    ],
)


def _form_data_to_terapia_params(form: dict[str, Any]) -> dict[str, Any]:
    return {
        "animal_id": (form.get("animal_id") or "").strip(),
        "voluntario_id": (form.get("voluntario_id") or "").strip(),
        "fecha": (form.get("fecha") or "").strip(),
        "descripcion": _opt(form.get("descripcion")),
    }


def _terapia_to_form_data(
    terapia: salud_service.Terapia,
) -> dict[str, Any]:
    return {
        "animal_id": terapia.animal_id,
        "voluntario_id": terapia.voluntario_id,
        "fecha": terapia.fecha,
        "descripcion": terapia.descripcion or "",
    }


def _actor_user_id(user: AuthenticatedUser) -> str | None:
    if isinstance(user, dict):
        uid = user.get("user_id")
        return str(uid) if uid is not None else None
    return None


def _render_terapia_form(
    request: Request,
    user: AuthenticatedUser,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    return _templates.TemplateResponse(
        request=request,
        name="salud/terapia_form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "form_action": form_action,
        },
        status_code=status_code,
    )


def _render_terapia_form_error(
    request: Request,
    user: AuthenticatedUser,
    params: dict[str, Any],
    exc: Exception,
    form_action: str,
) -> HTMLResponse:
    """Render the terapia form with an error message derived from ``exc``."""
    if isinstance(exc, ValueError):
        return _render_terapia_form(
            request, user, params,
            f"No se pudo guardar la terapia: {exc}",
            form_action,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    # InsForgeError — log and show a user-friendly message
    log_safe(
        "salud.terapia.backend_error",
        form_action=form_action,
    )
    return _render_terapia_form(
        request, user, params,
        "No se pudo contactar con el backend. Inténtalo de nuevo.",
        form_action,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# --- list ------------------------------------------------------------------


@router.get("/terapias", response_class=HTMLResponse)
def list_terapias_view(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    animal_id: str | None = None,
):
    """List active terapias; ``?animal_id=`` filters to one animal."""
    if (early := return_early_if_response(user)) is not None:
        return early
    animal_id = (animal_id or "").strip() or None
    terapias = salud_service.list_terapias(client, animal_id=animal_id)
    return _templates.TemplateResponse(
        request=request,
        name="salud/list_terapias.html",
        context={
            "user": user,
            "terapias": terapias,
            "animal_id": animal_id or "",
        },
    )


# --- new (form) -----------------------------------------------------------


@router.get("/terapias/new", response_class=HTMLResponse)
def new_terapia_form(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Empty form for a new terapia."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_terapia_form(
        request, user, {}, None, "/terapias", status.HTTP_200_OK
    )


# --- create (submit) ------------------------------------------------------


@router.post("/terapias", response_class=HTMLResponse)
def create_terapia_view(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    animal_id: Annotated[str, Form()],
    voluntario_id: Annotated[str, Form()],
    fecha: Annotated[str, Form()],
    descripcion: Annotated[str | None, Form()] = None,
):
    """Create a terapia; redirect to detail on success.

    Write endpoint — ``require_permission(WRITE_SALUD)`` rejects ``reader``
    with 403. On ``ValueError`` (FK activo check, missing required field)
    or ``InsForgeError``, the form is re-rendered with a 422.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    params = _form_data_to_terapia_params({
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "descripcion": descripcion,
    })
    try:
        terapia = salud_service.create_terapia(
            client,
            params,
            actor_user_id=_actor_user_id(user),
        )
    except Exception as exc:
        return _render_terapia_form_error(
            request, user, params, exc, "/terapias"
        )
    return RedirectResponse(
        url=f"/terapias/{terapia.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ----------------------------------------------------------------


@router.get("/terapias/{terapia_id}", response_class=HTMLResponse)
def terapia_detail(
    terapia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Detail view with its recomendaciones; 404 when the id is missing."""
    if (early := return_early_if_response(user)) is not None:
        return early
    terapia = salud_service.get_terapia_by_id(client, terapia_id)
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    recomendaciones = salud_service.list_recomendaciones(client, terapia_id)
    return _templates.TemplateResponse(
        request=request,
        name="salud/terapia_detail.html",
        context={
            "user": user,
            "terapia": terapia,
            "recomendaciones": recomendaciones,
        },
    )


# --- edit (form) ----------------------------------------------------------


@router.get("/terapias/{terapia_id}/edit", response_class=HTMLResponse)
def edit_terapia_form(
    terapia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Edit form prefilled from the persisted row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    terapia = salud_service.get_terapia_by_id(client, terapia_id)
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_terapia_form(
        request,
        user,
        _terapia_to_form_data(terapia),
        None,
        f"/terapias/{terapia_id}/update",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/terapias/{terapia_id}/update", response_class=HTMLResponse)
def update_terapia_view(
    terapia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    animal_id: Annotated[str, Form()],
    voluntario_id: Annotated[str, Form()],
    fecha: Annotated[str, Form()],
    descripcion: Annotated[str | None, Form()] = None,
):
    """Update an existing terapia; redirect to detail on success.

    Write endpoint — same error-handling contract as ``create_terapia_view``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    params = _form_data_to_terapia_params({
        "animal_id": animal_id,
        "voluntario_id": voluntario_id,
        "fecha": fecha,
        "descripcion": descripcion,
    })
    try:
        terapia = salud_service.update_terapia(
            client,
            terapia_id,
            params,
            actor_user_id=_actor_user_id(user),
        )
    except Exception as exc:
        return _render_terapia_form_error(
            request, user, params, exc, f"/terapias/{terapia_id}/update"
        )
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/terapias/{terapia_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- delete (soft) --------------------------------------------------------


@router.post("/terapias/{terapia_id}/delete", response_class=HTMLResponse)
def delete_terapia_view(
    terapia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Soft-delete via ``salud_service.delete_terapia``.

    Write endpoint. 409 when the terapia has pending recommendations
    (completada=false). 404 when the id does not exist.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        deleted = salud_service.delete_terapia(
            client,
            terapia_id,
            actor_user_id=_actor_user_id(user),
        )
    except salud_service.TerapiaHasPendingRecomendaciones:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar la terapia: tiene recomendaciones pendientes.",
        ) from None
    except InsForgeError as exc:
        log_safe(
            "salud.delete_terapia.backend_error",
            terapia_id=terapia_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/terapias", status_code=status.HTTP_303_SEE_OTHER
    )


# --- recomendaciones -------------------------------------------------------


@router.get("/terapias/{terapia_id}/recomendaciones", response_class=HTMLResponse)
def list_recomendaciones_view(
    terapia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """List active recomendaciones for a terapia."""
    if (early := return_early_if_response(user)) is not None:
        return early
    terapia = salud_service.get_terapia_by_id(client, terapia_id)
    if terapia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    recomendaciones = salud_service.list_recomendaciones(client, terapia_id)
    return _templates.TemplateResponse(
        request=request,
        name="salud/recomendaciones_list.html",
        context={
            "user": user,
            "terapia": terapia,
            "recomendaciones": recomendaciones,
        },
    )


@router.post("/terapias/{terapia_id}/recomendaciones", response_class=HTMLResponse)
def create_recomendacion_view(
    terapia_id: str,
    request: Request,
    fecha: Annotated[str, Form()],
    texto: Annotated[str, Form()],
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Create a recomendacion linked to the terapia.

    Write endpoint — requires ``WRITE_SALUD``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    params = {
        "terapia_id": terapia_id,
        "fecha": fecha.strip(),
        "texto": texto.strip(),
    }
    try:
        salud_service.create_recomendacion(
            client,
            params,
            actor_user_id=_actor_user_id(user),
        )
    except ValueError as exc:
        # Could not create — either terapia missing or inactive
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except InsForgeError as exc:
        log_safe(
            "salud.create_recomendacion.backend_error",
            terapia_id=terapia_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    return RedirectResponse(
        url=f"/terapias/{terapia_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.patch("/recomendaciones/{recomendacion_id}", response_class=HTMLResponse)
def complete_recomendacion_view(
    recomendacion_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Mark a recomendacion as completed (``completada=true``).

    Write endpoint — requires ``WRITE_SALUD``.
    Returns 404 if the recomendacion is not found or already completed.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        recomendacion = salud_service.complete_recomendacion(
            client,
            recomendacion_id,
            actor_user_id=_actor_user_id(user),
        )
    except salud_service.RecomendacionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except InsForgeError as exc:
        log_safe(
            "salud.complete_recomendacion.backend_error",
            recomendacion_id=recomendacion_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    return RedirectResponse(
        url=f"/terapias/{recomendacion.terapia_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.delete("/recomendaciones/{recomendacion_id}", response_class=HTMLResponse)
def delete_recomendacion_view(
    recomendacion_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Soft-delete a recomendacion.

    Write endpoint — requires ``WRITE_SALUD``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    # Get the terapia_id before deleting so we can redirect correctly
    recomendacion = salud_service.get_recomendacion_by_id(client, recomendacion_id)
    if recomendacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    terapia_id = recomendacion.terapia_id

    try:
        deleted = salud_service.delete_recomendacion(
            client,
            recomendacion_id,
            actor_user_id=_actor_user_id(user),
        )
    except InsForgeError as exc:
        log_safe(
            "salud.delete_recomendacion.backend_error",
            recomendacion_id=recomendacion_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/terapias/{terapia_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
