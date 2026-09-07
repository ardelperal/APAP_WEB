"""Catalog CRUD routes for FOSTER-04 (#46) materiales.

PR B scope: the catalog CRUD endpoints under ``/materiales``. Routes
are thin HTTP glue — every data access delegates to
``app.modules.materiales.service`` (AGENTS.md §1, zero SQL in routes).

Endpoints (mounted at ``/materiales`` by ``app/main.py``):

- ``GET  /materiales``                       list of active catalog rows.
- ``GET  /materiales/new``                  empty create form.
- ``POST /materiales``                       create; 303 to detail; 409 on
                                                duplicate natural-key; 422
                                                on validation; 403 without
                                                writer+CSRF.
- ``GET  /materiales/{id}``                 detail view (assigned-estancias
                                                section is a stub for PR C
                                                to fill in).
- ``GET  /materiales/{id}/edit``            edit form prefilled.
- ``POST /materiales/{id}/edit``            update; 303 to detail.
- ``POST /materiales/{id}/deactivate``      soft-delete; 303 to list.

RBAC (REQ-FOSTER-04-03, AGENTS.md §17.2 + issue #144):

- GET routes use ``require_authorized_user`` (any reader+ can view).
- POST routes use ``require_writer_user`` (writers + developers + key_user).

Conflict mapping (PR-5B pattern, ``AcogidaConflictError`` /
``AdopcionConflictError`` precedent): the catalog's
``UNIQUE (material, tamano, color)`` constraint is DB-enforced. The
service translates the resulting ``BackendError(23505)`` to
``materiales_service.MaterialConflictError``; the route maps that to a
distinct HTTP 409 + a Spanish actionable message (NOT the generic 422)
so the operator sees a clear "ya existe material con esa combinación
material+tamaño+color" hint.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core._module_helpers._crud_flow import render_detail, render_edit_form
from app.core._module_helpers._form_render import make_render_form
from app.core.auth_dependencies import (
    AuthenticatedUser,
    get_local_postgres_executor_dep,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.data_access import SqlExecutor
from app.core.forms import optional_value as _opt
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.materiales import service as materiales_service
from app.modules.materiales.forms import MaterialForm

router = APIRouter(prefix="/materiales", tags=["materiales"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# --- helpers --------------------------------------------------------------


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Map the create/edit form dict to the service-param shape.

    The service's ``create_material`` / ``update_material`` expect the
    natural-key trio (``material``, ``tamano``, ``color``) and the free
    ``observaciones`` field. Blank observations collapse to ``None``
    so the DB stores NULL.
    """
    return {
        "material": form.get("material"),
        "tamano": form.get("tamano"),
        "color": form.get("color"),
        "observaciones": _opt(form.get("observaciones")),
    }


def _material_to_form_data(
    material: materiales_service.Material,
) -> dict[str, Any]:
    """Reverse of ``_form_data_to_params`` — prefill the edit form.

    Slots the optional fields' ``None`` back to ``""`` so the HTML
    ``value=`` attribute renders cleanly without a literal ``None``
    string in the operator's browser.
    """
    return {
        "material": material.material,
        "tamano": material.tamano,
        "color": material.color,
        "observaciones": material.observaciones or "",
    }


# ``_render_form`` is a partial of ``render_module_form`` that bakes in the
# module's templates and template name (issue #681 — JSCPD ratchet).
# The wrapper signature is unchanged so the existing 7 call sites
# ``_render_form(request, user, form_data, error, form_action[, status_code])``
# continue to work without edits.
_render_form = make_render_form(_templates, "materiales/form.html")
_edit_material_form: Any = partial(
    render_edit_form,
    fetch=materiales_service.get_material_by_id,
    to_form_data=_material_to_form_data,
    render_form=_render_form,
    form_action="/materiales/{entity_id}/update",
)



# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_materiales_view(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Active catalog list. Delegates to ``materiales_service.list_materials``.

    The catalog list view shows active rows only (the ``activos_solo=True``
    default in the service). Phase 6c will add an admin view that toggles
    ``activos_solo=False`` to see the historical / soft-deleted rows; out
    of #46 scope.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    materiales = materiales_service.list_materials(client, activos_solo=True)
    return _templates.TemplateResponse(
        request=request,
        name="materiales/list.html",
        context={"user": user, "materiales": materiales},
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_material_form(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
):
    """Empty create form.

    Use ``require_authorized_user`` (NOT ``require_writer_user``) here
    so the reader can preview the form; the POST handler is the one
    that enforces writer+CSRF. Same convention used in
    ``app/modules/foster/routes.py::new_casa_acogida_form``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/materiales")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_material_view(
    request: Request,
    form: Annotated[MaterialForm, Form()],
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):  # noqa: PLR0913  # refactored to MaterialForm
    """Procesa el submit del formulario de alta. En exito, redirect al detalle.

    Distinct HTTP status codes per failure mode (operator UX):

    - 303 to ``/materiales/{id}`` on success.
    - 409 + Spanish actionable message on duplicate natural-key
      (``MaterialConflictError``). Mirrors the
      ``AcogidaConflictError``/``AdopcionConflictError`` precedent.
    - 422 HTML re-render + operator input preserved on any other
      validation error (``ValueError`` from the service, e.g. blank
      required field).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(form.model_dump())
    try:
        new_material = materiales_service.create_material(client, form_data)
    except materiales_service.MaterialConflictError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"ya existe material con esa combinación material+tamaño+color: {exc}",
            "/materiales",
            status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar el material: {exc}",
            "/materiales",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/materiales/{new_material.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- detail ---------------------------------------------------------------


@router.get("/{material_id}", response_class=HTMLResponse)
def material_detail(
    material_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Detail view. Returns 404 when the row is missing (issue #681 — JSCPD ratchet).

    PR C integrates the assigned-estancias section (uses
    ``list_materials_for_estancia``); for PR B this section is rendered
    as an empty placeholder per the SDD tasks plan (#15905 §B.2.3).
    """
    return render_detail(
        templates=_templates,
        request=request,
        user=user,
        client=client,
        entity_id=material_id,
        fetch=materiales_service.get_material_by_id,
        template_name="materiales/detail.html",
        context_key="material",
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{material_id}/edit", response_class=HTMLResponse)
def edit_material_form(
    material_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Edit form prefilled with the persisted row (issue #681 — JSCPD ratchet).

    Returns 404 when the row is missing so the operator never sees a
    half-rendered form for a stale URL. The form action posts to
    ``/materiales/{id}/edit`` (same path as the GET — the verb in the
    HTTP method distinguishes intent).
    """
    return _edit_material_form(
        request=request, user=user, client=client, entity_id=material_id,
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{material_id}/edit", response_class=HTMLResponse)
def update_material_view(
    material_id: str,
    request: Request,
    form: Annotated[MaterialForm, Form()],
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):  # noqa: PLR0913  # refactored to MaterialForm
    """Procesa el submit del formulario de edicion. En exito, redirect al detalle.

    Same 3-way status contract as ``create_material_view``:

    - 303 to ``/materiales/{id}`` on success.
    - 409 on ``MaterialConflictError`` (an update that produces a
      duplicate natural-key against a different row — the DB still
      fires ``UNIQUE``).
    - 422 HTML re-render on ``ValueError`` (e.g. blank required field).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(form.model_dump())
    try:
        updated = materiales_service.update_material(
            client, material_id, form_data
        )
    except materiales_service.MaterialConflictError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"ya existe material con esa combinación material+tamaño+color: {exc}",
            f"/materiales/{material_id}/edit",
            status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar el material: {exc}",
            f"/materiales/{material_id}/edit",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/materiales/{material_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- deactivate (soft delete) --------------------------------------------


@router.post("/{material_id}/deactivate", response_class=HTMLResponse)
def deactivate_material_view(
    material_id: str,
    _request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_MATERIALES))],
    client: Annotated[SqlExecutor, Depends(get_local_postgres_executor_dep)],
):
    """Soft-delete via ``materiales_service.deactivate_material``.

    Returns 303 to ``/materiales`` on success. Returns 404 when the
    service signals the row was already inactive OR does not exist
    (the service folds both into a single ``False`` sentinel — same
    shape as ``app/modules/foster/routes.py::delete_casa_acogida_view``).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not materiales_service.deactivate_material(client, material_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/materiales",
        status_code=status.HTTP_303_SEE_OTHER,
    )
