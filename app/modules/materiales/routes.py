"""Catalog CRUD routes for FOSTER-04 (#46) materiales.

PR 4 of issue #752 (materiales hexagonal refactor): the catalog
CRUD endpoints under ``/materiales`` now depend on
:class:`MaterialesPort` via :func:`get_materiales_port` and call
the application-layer use cases in
:mod:`app.modules.materiales.application` — not the legacy
``service.py``. Routes are thin HTTP glue; every data access
delegates to the use case, which delegates to the port, which
delegates to the LocalBackend adapter (AGENTS.md §1, §22, §31).

Endpoints (mounted at ``/materiales`` by ``app/main.py``):

- ``GET  /materiales``                       list of active catalog rows.
- ``GET  /materiales/new``                  empty create form.
- ``POST /materiales``                       create; 303 to detail; 409 on
                                                    duplicate natural-key; 422
                                                    on validation; 403 without
                                                    writer+CSRF.
- ``GET  /materiales/{id}``                 detail view.
- ``GET  /materiales/{id}/edit``            edit form prefilled.
- ``POST /materiales/{id}/edit``            update; 303 to detail.
- ``POST /materiales/{id}/deactivate``      soft-delete; 303 to list.

RBAC (REQ-FOSTER-04-03, AGENTS.md §17.2 + issue #144):

- GET routes use ``require_authorized_user`` (any reader+ can view).
- POST routes use ``require_writer_user`` (writers + developers + key_user).

Conflict mapping (PR-5B pattern, ``AcogidaConflictError`` /
``AdopcionConflictError`` precedent): the catalog's
``UNIQUE (material, tamano, color)`` constraint is DB-enforced. The
adapter translates the resulting ``BackendError(23505)`` to
``MaterialConflictError``; the use case re-raises the conflict
exception; the route maps that to a distinct HTTP 409 + a Spanish
actionable message (NOT the generic 422) so the operator sees a
clear "ya existe material con esa combinación material+tamaño+color"
hint.

Validation mapping: ``MaterialValidationError`` (the application
exception raised by the use case on blank required fields) maps
to HTTP 422 with an HTML re-render of the form. Mirrors the
``AnimalValidationError`` precedent at
``app/modules/animals/routes.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core._module_helpers._crud_flow import render_detail, render_edit_form
from app.core._module_helpers._form_render import make_render_form
from app.core.auth_dependencies import (
    AuthenticatedUser,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.forms import optional_value as _opt
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.materiales import application as materiales_application
from app.modules.materiales.application.create_material import MaterialValidationError
from app.modules.materiales.di import get_materiales_port
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material
from app.modules.materiales.forms import MaterialForm
from app.modules.materiales.ports.materiales_port import MaterialesPort

router = APIRouter(prefix="/materiales", tags=["materiales"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


# --- helpers --------------------------------------------------------------


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Map the create/edit form dict to the use-case kwargs shape."""
    return {
        "material": form.get("material"),
        "tamano": form.get("tamano"),
        "color": form.get("color"),
        "observaciones": _opt(form.get("observaciones")),
    }


def _material_to_form_data(material: Material) -> dict[str, Any]:
    """Reverse of ``_form_data_to_params`` — prefill the edit form."""
    return {
        "material": material.material,
        "tamano": material.tamano,
        "color": material.color,
        "observaciones": material.observaciones or "",
    }


def _make_get_by_id_fetch(port: MaterialesPort):
    """Return a ``fetch(client, entity_id) -> Material | None`` for the helpers.

    The :func:`render_detail` and :func:`render_edit_form` helpers in
    :mod:`app.core._module_helpers._crud_flow` were written for the
    pre-hexagonal era: they pre-bind ``client`` (the SqlExecutor) as
    the first arg of the fetch callable. PR 4 swaps the first arg
    from a SqlExecutor to a :class:`MaterialesPort`; the helper
    signature is unchanged but the fetch callable must ignore the
    first arg (the port is already captured in the route's closure)
    and call the use case directly.
    """
    def fetch(_unused_port: MaterialesPort, entity_id: str) -> Material | None:
        return materiales_application.get_material_by_id(port, entity_id)
    return fetch


# ``_render_form`` is a partial of ``render_module_form`` that bakes in the
# module's templates and template name (issue #681 — JSCPD ratchet).
# The wrapper signature is unchanged so the existing call sites
# ``_render_form(request, user, form_data, error, form_action[, status_code])``
# continue to work without edits.
_render_form = make_render_form(_templates, "materiales/form.html")
# ``_edit_material_form`` is bound at request time (inside the handler)
# because the fetch callable closes over the request-scoped port.
# The module-level constant stays for backward compatibility with the
# import sites that test the binding; the actual call happens in
# ``edit_material_form`` below.


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_materiales_view(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):
    """Active catalog list. Delegates to ``application.list_materials``.

    The catalog list view shows active rows only (the ``activos_solo=True``
    default in the use case). Phase 6c will add an admin view that toggles
    ``activos_solo=False`` to see the historical / soft-deleted rows; out
    of #46 scope.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    materiales = materiales_application.list_materials(port, activos_solo=True)
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
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):  # noqa: PLR0913  # refactored to MaterialForm
    """Procesa el submit del formulario de alta. En exito, redirect al detalle.

    Distinct HTTP status codes per failure mode (operator UX):

    - 303 to ``/materiales/{id}`` on success.
    - 409 + Spanish actionable message on duplicate natural-key
      (``MaterialConflictError``).
    - 422 HTML re-render + operator input preserved on
      ``MaterialValidationError`` (blank required field, raised by the
      use case before the port sees anything).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(form.model_dump())
    try:
        new_material = materiales_application.create_material(
            port,
            material=form_data["material"],
            tamano=form_data["tamano"],
            color=form_data["color"],
            observaciones=form_data["observaciones"],
        )
    except MaterialConflictError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"ya existe material con esa combinación material+tamaño+color: {exc}",
            "/materiales",
            status.HTTP_409_CONFLICT,
        )
    except MaterialValidationError as exc:
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
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):
    return render_detail(
        templates=_templates,
        request=request,
        user=user,
        client=port,  # noqa: ARG001 — passed through to fetch but ignored inside
        entity_id=material_id,
        fetch=_make_get_by_id_fetch(port),
        template_name="materiales/detail.html",
        context_key="material",
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{material_id}/edit", response_class=HTMLResponse)
def edit_material_form(
    material_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_MATERIALES))],
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):
    return render_edit_form(
        request=request,
        user=user,
        client=port,  # noqa: ARG001 — see ``_make_get_by_id_fetch``
        entity_id=material_id,
        fetch=_make_get_by_id_fetch(port),
        to_form_data=_material_to_form_data,
        render_form=_render_form,
        form_action="/materiales/{entity_id}/edit",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{material_id}/edit", response_class=HTMLResponse)
def update_material_view(
    material_id: str,
    request: Request,
    form: Annotated[MaterialForm, Form()],
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_MATERIALES))],
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):  # noqa: PLR0913  # refactored to MaterialForm
    """Procesa el submit del formulario de edicion. En exito, redirect al detalle.

    Same 3-way status contract as ``create_material_view``:

    - 303 to ``/materiales/{id}`` on success.
    - 409 on ``MaterialConflictError`` (an update that produces a
      duplicate natural-key against a different row — the DB still
      fires ``UNIQUE``).
    - 422 HTML re-render on ``MaterialValidationError``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data: dict[str, Any] = _form_data_to_params(form.model_dump())
    try:
        updated = materiales_application.update_material(
            port,
            material_id,
            material=form_data["material"],
            tamano=form_data["tamano"],
            color=form_data["color"],
            observaciones=form_data["observaciones"],
        )
    except MaterialConflictError as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"ya existe material con esa combinación material+tamaño+color: {exc}",
            f"/materiales/{material_id}/edit",
            status.HTTP_409_CONFLICT,
        )
    except MaterialValidationError as exc:
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
    port: Annotated[MaterialesPort, Depends(get_materiales_port)],
):
    """Soft-delete via ``application.deactivate_material``.

    Returns 303 to ``/materiales`` on success. Returns 404 when the
    use case signals the row was already inactive OR does not exist
    (the port folds both into a single ``False`` sentinel — same
    shape as ``app/modules/foster/routes.py::delete_casa_acogida_view``).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not materiales_application.deactivate_material(port, material_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/materiales",
        status_code=status.HTTP_303_SEE_OTHER,
    )
