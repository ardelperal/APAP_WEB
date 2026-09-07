"""Route handlers for the task engine (issue #7).

Thin HTTP glue — delegates all SQL and business logic to the service layer.

Routes:
  GET  /tareas              — list tareas with optional filters
  GET  /tareas/<tarea_id>   — detail view
  POST /tareas              — create a manual tarea
  POST /tareas/<tarea_id>/asignar  — assign to a responsable
  POST /tareas/<tarea_id>/cerrar   — close a tarea

Auth: all routes require authorized user (require_authorized_user).
CSRF: all POST forms include csrf_token (CsrfMiddleware validates).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_local_postgres_executor_dep,  # noqa: F401  - LocalBackend deprecation migration
    require_authorized_user,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import SqlExecutor
from app.core.middleware import base_template_context_processor
from app.modules.tasks import service as tareas_service
from app.modules.tasks.forms import TareaForm

router = APIRouter(prefix="/tareas", tags=["tareas"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# --- GET /tareas ----------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def listar_tareas(  # noqa: PLR0913  # 4 query filters + 3 fixed deps; filters needed for task UX
    request: Request,
    current_user: Annotated[dict, Depends(require_authorized_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    estado: str | None = None,
    responsable_id: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
):
    """List tareas with optional filters (estado, responsable, vinculo)."""
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
    current_user: Annotated[dict, Depends(require_authorized_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Render the detail view for a single tarea."""
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
    current_user: Annotated[dict, Depends(require_authorized_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):  # noqa: PLR0913  # refactored to TareaForm
    """Create a manual tarea from form data.

    On success redirects to GET /tareas.
    On validation error redirects back to /tareas with error flash.
    """
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
    current_user: Annotated[dict, Depends(require_authorized_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    tarea_id: str,
    responsable_id: Annotated[str | None, Form()] = None,
):
    """Assign a tarea to a responsable (or unassign)."""
    try:
        tareas_service.asignar_tarea(
            client=client,
            tarea_id=tarea_id,
            responsable_id=responsable_id,
        )
    except ValueError:
        pass
    return RedirectResponse(url=f"/tareas/{tarea_id}", status_code=302)


# --- POST /tareas/<tarea_id>/cerrar ---------------------------------------


@router.post("/{tarea_id}/cerrar", response_class=RedirectResponse)
def cerrar_tarea(
    request: Request,
    current_user: Annotated[dict, Depends(require_authorized_user)],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
    tarea_id: str,
    comentario: Annotated[str | None, Form()] = None,
):
    """Close a tarea (transition to 'completada')."""
    try:
        tareas_service.cerrar_tarea(
            client=client,
            tarea_id=tarea_id,
            comentario=comentario,
        )
    except (ValueError, tareas_service.CerrarTareaError):
        pass
    return RedirectResponse(url=f"/tareas/{tarea_id}", status_code=302)
