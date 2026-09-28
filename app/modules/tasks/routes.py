"""Route handlers for the task engine (issue #7).

Thin HTTP glue — delegates all SQL and business logic to the service layer.

Routes:
  GET  /tareas              — list tareas with optional filters
  GET  /tareas/<tarea_id>   — detail view
  POST /tareas              — create a manual tarea
  POST /tareas/<tarea_id>/asignar  — assign to a responsable
  POST /tareas/<tarea_id>/cerrar   — close a tarea

Auth (issue #1019): the RBAC matrix has no ``read:tareas``/
``write:tareas`` permission and this slice must not invent new
permissions, so the reads keep ``require_authorized_user`` composed
with the module-local ``require_known_rol`` dep — fail-closed on
unknown rol strings, same contract as D-44 (a ghost rol gets 403).
The write routes land on ``require_writer_user`` (legacy writer set:
developer/admin/key_user; ``reader`` is read-only).
CSRF: all POST forms include csrf_token (CsrfMiddleware validates).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_local_postgres_executor_dep,  # noqa: F401  - LocalBackend deprecation migration
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.core.middleware import base_template_context_processor, current_path_context_processor
from app.core.rbac import Role
from app.core.roles import Rol
from app.modules.tasks import service as tareas_service
from app.modules.tasks.forms import TareaForm

router = APIRouter(prefix="/tareas", tags=["tareas"])

#: Every rol value the system defines: the legacy ``Rol`` enum (the only
#: roles the admin panel can assign today) plus the new RBAC ``Role``
#: enum. Composed from the public enums — no role list is replicated
#: here (apap-security HR-3). A session whose ``rol`` is not in this set
#: (typo, ghost string) is denied 403 — the D-44 fail-closed contract
#: applied to the tareas reads, which cannot ride ``require_permission``
#: because the matrix has no tareas permission (issue #1019).
_KNOWN_ROL_VALUES: frozenset[str] = frozenset(
    r.value for r in Rol
) | frozenset(r.value for r in Role)


def require_known_rol(
    user: Response | dict = Depends(require_authorized_user),
) -> Response | dict:
    """Fail-closed rol-value validation for the ``/tareas`` reads (issue #1019).

    Composes on ``require_authorized_user`` (session + revalidation) and
    adds the missing check: a session whose ``rol`` value is not one of
    the canonical roles raises 403 BEFORE the handler runs, mirroring the
    ``require_permission`` D-44 contract. Allowlisted in
    ``tests/test_rbac_route_guardian.py`` with this justification.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    rol = user.get("rol") if isinstance(user, dict) else None
    if rol not in _KNOWN_ROL_VALUES:
        log_safe(
            "auth.denied",
            reason="permission_denied",
            user_id=user.get("user_id") if isinstance(user, dict) else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )
    return user

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor, current_path_context_processor],
)


def _tarea_redirect(tarea_id: str) -> RedirectResponse:
    """Redirect to the tarea detail URL after validating the id (issue #1038).

    ``tarea_id`` is semantically a Postgres UUID (every query casts
    ``::uuid``), so any value that does not parse as one never reaches
    the redirect target: the handler logs via ``log_safe`` and falls
    back to the ``/tareas`` list constant. This closes the CodeQL
    ``py/url-redirection`` findings (#30, #31, #124, #125) — no
    f-string interpolation of an unvalidated id into a redirect URL.
    """
    try:
        uuid.UUID(tarea_id)
    except (ValueError, TypeError, AttributeError):
        log_safe(
            "tareas.redirect_invalid_id",
            reason="invalid_tarea_id",
        )
        return RedirectResponse(url="/tareas", status_code=302)
    return RedirectResponse(url=f"/tareas/{tarea_id}", status_code=302)


# --- GET /tareas ----------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def listar_tareas(  # noqa: PLR0913  # 4 query filters + 3 fixed deps; filters needed for task UX
    request: Request,
    current_user: Annotated[dict, Depends(require_known_rol)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    estado: str | None = None,
    responsable_id: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
):
    """List tareas with optional filters (estado, responsable, vinculo)."""
    # Issue #1002 (JD-B-001): propagate the auth-denial redirect. Without
    # this, a deactivated user with a still-valid session got the page
    # rendered (require_authorized_user's RedirectResponse was ignored).
    if (early := return_early_if_response(current_user)) is not None:
        return early
    try:
        tareas = tareas_service.listar_tareas(
            client=client,
            estado=estado,
            responsable_id=responsable_id,
            vinculo_tipo=vinculo_tipo,
            vinculo_id=vinculo_id,
        )
    except ValueError:
        # Invalid filter value — show empty list with error context
        tareas = []

    # Load the template (shared base so we reuse the design system)
    base_template = "tareas/list.html"
    template_path = _TEMPLATES_DIR / base_template
    if not template_path.exists():
        # Fallback to index-like rendering inline
        return _render_tareas_list(request, tareas, current_user, estado=estado)

    return _templates.TemplateResponse(
        request=request,
        name=base_template,
        context={
            "tareas": tareas,
            "current_user": current_user,
            "filter_estado": estado,
            "filter_responsable_id": responsable_id,
        },
    )


def _render_tareas_list(
    request: Request,
    tareas: list[tareas_service.Tarea],
    current_user: dict,
    estado: str | None = None,
) -> HTMLResponse:
    """Render a simple tareas list without a dedicated template."""
    return _templates.TemplateResponse(
        request=request,
        name="base.html",
        context={
            "request": request,
            "tareas": tareas,
            "current_user": current_user,
            "filter_estado": estado,
        },
    )


# --- GET /tareas/<tarea_id> ----------------------------------------------


@router.get("/{tarea_id}", response_class=HTMLResponse)
def detalle_tarea(
    request: Request,
    tarea_id: str,
    current_user: Annotated[dict, Depends(require_known_rol)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Render the detail view for a single tarea."""
    # Issue #1002: propagate the auth-denial redirect (see listar_tareas).
    if (early := return_early_if_response(current_user)) is not None:
        return early
    tarea = tareas_service.obtener_tarea(client=client, tarea_id=tarea_id)
    if tarea is None:
        return RedirectResponse(url="/tareas", status_code=302)

    return _templates.TemplateResponse(
        request=request,
        name="tareas/detail.html",
        context={
            "tarea": tarea,
            "current_user": current_user,
        },
    )


# --- POST /tareas ---------------------------------------------------------


@router.post("", response_class=RedirectResponse)
def crear_tarea(
    request: Request,
    form: Annotated[TareaForm, Form()],
    current_user: Annotated[dict, Depends(require_writer_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):  # noqa: PLR0913  # refactored to TareaForm
    """Create a manual tarea from form data.

    On success redirects to GET /tareas.
    On validation error redirects back to /tareas with error flash.
    """
    # Issue #1002: propagate the auth-denial redirect — pre-fix a
    # deactivated user's POST created the tarea (silent state mutation).
    if (early := return_early_if_response(current_user)) is not None:
        return early
    try:
        tareas_service.crear_tarea(
            client=client,
            tipo=form.tipo,
            origen=form.origen,
            prioridad=form.prioridad,
            vencimiento_at=form.vencimiento_at,
            vinculo_tipo=form.vinculo_tipo,
            vinculo_id=form.vinculo_id,
        )
    except ValueError:
        # Redirect back to list on validation error
        pass
    return RedirectResponse(url="/tareas", status_code=302)


# --- POST /tareas/<tarea_id>/asignar -------------------------------------


@router.post("/{tarea_id}/asignar", response_class=RedirectResponse)
def asignar_tarea(
    request: Request,
    current_user: Annotated[dict, Depends(require_writer_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    tarea_id: str,
    responsable_id: Annotated[str | None, Form()] = None,
):
    """Assign a tarea to a responsable (or unassign)."""
    # Issue #1002: propagate the auth-denial redirect (see crear_tarea).
    if (early := return_early_if_response(current_user)) is not None:
        return early
    try:
        tareas_service.asignar_tarea(
            client=client,
            tarea_id=tarea_id,
            responsable_id=responsable_id,
        )
    except ValueError:
        pass
    return _tarea_redirect(tarea_id)


# --- POST /tareas/<tarea_id>/cerrar ---------------------------------------


@router.post("/{tarea_id}/cerrar", response_class=RedirectResponse)
def cerrar_tarea(
    request: Request,
    current_user: Annotated[dict, Depends(require_writer_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    tarea_id: str,
    comentario: Annotated[str | None, Form()] = None,
):
    """Close a tarea (transition to 'completada')."""
    # Issue #1002: propagate the auth-denial redirect (see crear_tarea).
    if (early := return_early_if_response(current_user)) is not None:
        return early
    try:
        tareas_service.cerrar_tarea(
            client=client,
            tarea_id=tarea_id,
            comentario=comentario,
        )
    except (ValueError, tareas_service.CerrarTareaError):
        pass
    return _tarea_redirect(tarea_id)
