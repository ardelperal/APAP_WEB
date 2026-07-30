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
service translates the resulting ``InsForgeError(23505)`` to
``materiales_service.MaterialConflictError``; the route maps that to a
distinct HTTP 409 + a Spanish actionable message (NOT the generic 422)
so the operator sees a clear "ya existe material con esa combinación
material+tamaño+color" hint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    is_authenticated_user,
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.forms import optional_value as _opt
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.modules.materiales import service as materiales_service

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


def _render_form(
    request: Request,
    user: Any,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    """Render ``app/templates/materiales/form.html`` with a fixed context.

    Mirrors the ``_render_form`` precedent in
    ``app/modules/foster/routes.py`` (and the same pattern in
    adopciones / sanidad). Centralizes the template-name + context
    keys so each handler declares only the action and error string.
    """
    return _templates.TemplateResponse(
        request=request,
        name="materiales/form.html",
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
def list_materiales_view(
    request: Request,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Active catalog list. Delegates to ``materiales_service.list_materials``.

    The catalog list view shows active rows only (the ``activos_solo=True``
    default in the service). Phase 6c will add an admin view that toggles
    ``activos_solo=False`` to see the historical / soft-deleted rows; out
    of #46 scope.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
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
    user: Response | dict = Depends(require_authorized_user),
):
    """Empty create form.

    Use ``require_authorized_user`` (NOT ``require_writer_user``) here
    so the reader can preview the form; the POST handler is the one
    that enforces writer+CSRF. Same convention used in
    ``app/modules/foster/routes.py::new_casa_acogida_form``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    return _render_form(request, user, {}, None, "/materiales")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_material_view(
    request: Request,
    material: str = Form(...),
    tamano: str = Form(...),
    color: str = Form(...),
    observaciones: str | None = Form(None),
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
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
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    form_data: dict[str, Any] = _form_data_to_params(
        {
            "material": material,
            "tamano": tamano,
            "color": color,
            "observaciones": observaciones,
        }
    )
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
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Detail view. Returns 404 when the row is missing.

    PR C integrates the assigned-estancias section (uses
    ``list_materials_for_estancia``); for PR B this section is rendered
    as an empty placeholder per the SDD tasks plan (#15905 §B.2.3).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    material = materiales_service.get_material_by_id(client, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="materiales/detail.html",
        context={"user": user, "material": material},
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{material_id}/edit", response_class=HTMLResponse)
def edit_material_form(
    material_id: str,
    request: Request,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Edit form prefilled with the persisted row.

    Returns 404 when the row is missing so the operator never sees a
    half-rendered form for a stale URL. The form action posts to
    ``/materiales/{id}/edit`` (same path as the GET — the verb in the
    HTTP method distinguishes intent).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    material = materiales_service.get_material_by_id(client, material_id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _material_to_form_data(material),
        None,
        f"/materiales/{material_id}/edit",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{material_id}/edit", response_class=HTMLResponse)
def update_material_view(
    material_id: str,
    request: Request,
    material: str = Form(...),
    tamano: str = Form(...),
    color: str = Form(...),
    observaciones: str | None = Form(None),
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
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
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    form_data: dict[str, Any] = _form_data_to_params(
        {
            "material": material,
            "tamano": tamano,
            "color": color,
            "observaciones": observaciones,
        }
    )
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
    request: Request,
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete via ``materiales_service.deactivate_material``.

    Returns 303 to ``/materiales`` on success. Returns 404 when the
    service signals the row was already inactive OR does not exist
    (the service folds both into a single ``False`` sentinel — same
    shape as ``app/modules/foster/routes.py::delete_casa_acogida_view``).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    if not materiales_service.deactivate_material(client, material_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/materiales",
        status_code=status.HTTP_303_SEE_OTHER,
    )
