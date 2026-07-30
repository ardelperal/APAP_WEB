"""Route layer for HEALTH-01 sanidad (single-record CRUD).

Mirrors ``app/modules/adopciones/routes.py`` and
``app/modules/entradas/routes.py``: routes are pure HTTP / auth /
template glue. All data access delegates to ``app.modules.sanidad.service``.

The HEALTH-02 batch endpoint (issue #51) lives in
``app/modules/sanidad/batch_routes.py`` so each ``routes*.py`` file
stays under the AGENTS §21 / §28 budget (modular concern: the single-
record CRUD has its own concerns that would otherwise leak into the
batch handler).

Endpoints (mounted at ``/sanidad`` by ``app/main.py`` via the
combined router registered in ``routes_registry.py``):

- ``GET  /sanidad``                          list of active actuaciones
                                                  (with optional
                                                  ``?animal_id=`` filter).
- ``GET  /sanidad/new``                      empty form (with the
                                                  catalogos_pruebas
                                                  dropdown).
- ``POST /sanidad``                          create; redirect to
                                                  detail on success.
                                                  **Requires writer rol**
                                                  (issue #144).
- ``GET  /sanidad/{id}``                     detail view.
- ``GET  /sanidad/{id}/edit``                edit form prefilled.
- ``POST /sanidad/{id}/update``              update.
                                                  **Requires writer rol**
                                                  (issue #144).
- ``POST /sanidad/{id}/delete``              soft-delete.
                                                  **Requires writer rol**
                                                  (issue #144).

Batch endpoint (HEALTH-02, #51) — see ``batch_routes.py``:
- ``GET  /sanidad/batch/new``                empty 5-row batch form.
- ``POST /sanidad/actuaciones/batch``        atomic commit OR staging
                                                  preview. **Requires
                                                  writer rol.**

Auth model (issue #144): GET endpoints use ``require_authorized_user``
(read access stays open to any authorized operator). Write endpoints
(POST create / update / delete / batch) use ``require_writer_user``
which composes on ``require_authorized_user`` and rejects the ``reader``
rol with 403 BEFORE the handler runs.
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
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.logging import log_safe
from app.core.middleware import base_template_context_processor
from app.modules.sanidad import service as sanidad_service

router = APIRouter(prefix="/sanidad", tags=["sanidad"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
    ],
)


_FORM_FIELDS = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "tipo_actuacion_id",
    "veterinario",
    "observaciones",
    "material_utilizado",
)


def _opt(value: str | None) -> str | None:
    """Strip a string or convert empty to ``None`` for optional fields.

    Mirrors ``entradas/routes.py::_opt`` and ``adopciones/routes.py::_opt``.
    Lets the operator leave optional fields blank in the form (e.g.
    ``observaciones``) and have the service write NULL to the DB
    rather than an empty string.
    """
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Translate the raw form dict into the service's ``params`` schema."""
    return {key: _opt(form.get(key)) for key in _FORM_FIELDS}


def _actuacion_to_form_data(
    actuacion: sanidad_service.ActuacionSanitaria,
) -> dict[str, Any]:
    return {
        "animal_id": actuacion.animal_id,
        "voluntario_id": actuacion.voluntario_id or "",
        "fecha": actuacion.fecha,
        "tipo_actuacion_id": actuacion.tipo_actuacion_id or "",
        "veterinario": actuacion.veterinario or "",
        "observaciones": actuacion.observaciones or "",
        "material_utilizado": actuacion.material_utilizado or "",
    }


def _actor_user_id(user: Any) -> str | None:
    """Extract ``user_id`` from the auth payload for audit logging.

    ``user`` is the value returned by ``require_authorized_user`` (a
    dict-like). When the upstream dep returned a ``RedirectResponse``
    (no session, deactivated, etc.) we have already returned early via
    ``return_early_if_response``, so this only sees a dict.
    """
    if isinstance(user, dict):
        uid = user.get("user_id")
        return str(uid) if uid is not None else None
    return None


def _render_form(
    request: Request,
    user: Any,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    catalogos_pruebas: list[dict[str, Any]],
    status_code: int = status.HTTP_200_OK,
):
    """Render the create/edit form with the catalogos_pruebas dropdown populated.

    ``catalogos_pruebas`` is loaded once per request (kept small via the
    catalog query — ~13 rows after seed). The dropdown shows the catalog
    ``nombre`` and binds the row ``id`` (UUID) so the form sends a
    type-checked FK to the service.
    """
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/form.html",
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "form_action": form_action,
            "catalogos_pruebas": catalogos_pruebas,
        },
        status_code=status_code,
    )


def _load_catalogos_pruebas_for_form(
    client: InsForgeClient,
    *,
    context: str,
    actuacion_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load catalog rows for a form without making error recovery fragile."""
    try:
        return sanidad_service.list_catalogos_pruebas(client)
    except InsForgeError as exc:
        log_safe(
            "sanidad.catalogos_pruebas.load_failed",
            context=context,
            actuacion_id=actuacion_id,
            status_code=exc.status_code,
        )
        return []


def _render_backend_error(
    request: Request,
    user: Any,
    client: InsForgeClient,
    form_data: dict[str, Any],
    form_action: str,
    exc: InsForgeError,
    *,
    context: str,
    actuacion_id: str | None = None,
):
    """Render a sanidad form after a backend failure without retry loops."""
    log_safe(
        "sanidad.backend_error",
        context=context,
        actuacion_id=actuacion_id,
        status_code=exc.status_code,
    )
    catalogos = _load_catalogos_pruebas_for_form(
        client,
        context=f"{context}.recovery",
        actuacion_id=actuacion_id,
    )
    return _render_form(
        request,
        user,
        form_data,
        "No se pudo contactar con el backend. Inténtalo de nuevo en unos minutos.",
        form_action,
        catalogos,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# --- list -----------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_actuaciones_view(
    request: Request,
    animal_id: str | None = None,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """List active actuaciones; ``?animal_id=`` filters to one animal.

    Without the filter, the page shows the global list (most-recent
    first, hard LIMIT 100). With the filter, it shows only the clinical
    history of the chosen animal (the operator-facing use case is
    "open this animal's tab and see all its vacunas / desparasitaciones /
    analiticas in one place").
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    animal_id = (animal_id or "").strip() or None
    if animal_id:
        actuaciones = sanidad_service.search_actuaciones_by_animal(
            client, animal_id
        )
    else:
        actuaciones = sanidad_service.list_actuaciones_sanitarias(client)
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/list.html",
        context={
            "user": user,
            "actuaciones": actuaciones,
            "animal_id": animal_id or "",
        },
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_actuacion_form(
    request: Request,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Empty form for a new actuacion, with the catalogos_pruebas dropdown."""
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    catalogos = _load_catalogos_pruebas_for_form(client, context="new")
    return _render_form(
        request,
        user,
        {},
        None,
        "/sanidad",
        catalogos,
    )


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_actuacion_view(
    request: Request,
    animal_id: str = Form(...),
    voluntario_id: str | None = Form(None),
    fecha: str = Form(...),
    tipo_actuacion_id: str | None = Form(None),
    veterinario: str | None = Form(None),
    observaciones: str | None = Form(None),
    material_utilizado: str | None = Form(None),
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create an actuacion; redirect to detail on success.

    Write endpoint — ``require_writer_user`` rejects ``reader`` with 403
    BEFORE the handler runs (issue #144). On ``ValueError`` (D-24 reglas
    1+2/3, FK activo check, missing required field) or ``InsForgeError``
    (catalog FK violation), the form is re-rendered with a 422 carrying
    the operator's input so the form keeps its state.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "voluntario_id": voluntario_id,
            "fecha": fecha,
            "tipo_actuacion_id": tipo_actuacion_id,
            "veterinario": veterinario,
            "observaciones": observaciones,
            "material_utilizado": material_utilizado,
        }
    )
    try:
        actuacion = sanidad_service.create_actuacion_sanitaria(
            client,
            form_data,
            actor_user_id=_actor_user_id(user),
        )
    except ValueError as exc:
        catalogos = _load_catalogos_pruebas_for_form(
            client, context="create.validation"
        )
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar la actuación: {exc}",
            "/sanidad",
            catalogos,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        return _render_backend_error(
            request,
            user,
            client,
            form_data,
            "/sanidad",
            exc,
            context="create",
        )
    return RedirectResponse(
        url=f"/sanidad/{actuacion.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{actuacion_id}", response_class=HTMLResponse)
def actuacion_detail(
    actuacion_id: str,
    request: Request,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Detail view; 404 when the id is missing."""
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    actuacion = sanidad_service.get_actuacion_sanitaria_by_id(
        client, actuacion_id
    )
    if actuacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # Resolve the catalogos_pruebas entry for display in the detail page.
    # We pull the full list once and index by id; ~13 rows keeps this
    # cheap. If a future slice adds many more catalog rows, a targeted
    # SELECT by id is the next step.
    catalogos = _load_catalogos_pruebas_for_form(
        client, context="detail", actuacion_id=actuacion_id
    )
    catalogo_by_id = {str(row["id"]): row for row in catalogos}
    tipo_actuacion = (
        catalogo_by_id.get(actuacion.tipo_actuacion_id)
        if actuacion.tipo_actuacion_id
        else None
    )
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/detail.html",
        context={
            "user": user,
            "actuacion": actuacion,
            "tipo_actuacion": tipo_actuacion,
        },
    )


# --- edit (form) ----------------------------------------------------------


@router.get("/{actuacion_id}/edit", response_class=HTMLResponse)
def edit_actuacion_form(
    actuacion_id: str,
    request: Request,
    user: Response | dict = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Edit form prefilled from the persisted row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    actuacion = sanidad_service.get_actuacion_sanitaria_by_id(
        client, actuacion_id
    )
    if actuacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    catalogos = _load_catalogos_pruebas_for_form(
        client, context="edit", actuacion_id=actuacion_id
    )
    return _render_form(
        request,
        user,
        _actuacion_to_form_data(actuacion),
        None,
        f"/sanidad/{actuacion_id}/update",
        catalogos,
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{actuacion_id}/update", response_class=HTMLResponse)
def update_actuacion_view(
    actuacion_id: str,
    request: Request,
    animal_id: str = Form(...),
    voluntario_id: str | None = Form(None),
    fecha: str = Form(...),
    tipo_actuacion_id: str | None = Form(None),
    veterinario: str | None = Form(None),
    observaciones: str | None = Form(None),
    material_utilizado: str | None = Form(None),
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Update an existing actuacion; redirect to detail on success.

    Write endpoint — ``require_writer_user``. Same error-handling
    contract as ``create_actuacion_view`` (ValueError / InsForgeError →
    422 with form re-rendered + operator input preserved). Returns 404
    when the id does not exist.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "voluntario_id": voluntario_id,
            "fecha": fecha,
            "tipo_actuacion_id": tipo_actuacion_id,
            "veterinario": veterinario,
            "observaciones": observaciones,
            "material_utilizado": material_utilizado,
        }
    )
    try:
        actuacion = sanidad_service.update_actuacion_sanitaria(
            client,
            actuacion_id,
            form_data,
            actor_user_id=_actor_user_id(user),
        )
    except ValueError as exc:
        catalogos = _load_catalogos_pruebas_for_form(
            client, context="update.validation", actuacion_id=actuacion_id
        )
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar la actuación: {exc}",
            f"/sanidad/{actuacion_id}/update",
            catalogos,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        return _render_backend_error(
            request,
            user,
            client,
            form_data,
            f"/sanidad/{actuacion_id}/update",
            exc,
            context="update",
            actuacion_id=actuacion_id,
        )
    if actuacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/sanidad/{actuacion_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- delete (soft) -------------------------------------------------------


@router.post("/{actuacion_id}/delete", response_class=HTMLResponse)
def delete_actuacion_view(
    actuacion_id: str,
    request: Request,
    user: Response | dict = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete via ``sanidad_service.delete_actuacion_sanitaria``.

    Write endpoint — ``require_writer_user`` rejects ``reader`` with
    403. 404 when the id does not exist (or is already inactive).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not is_authenticated_user(user):  # pragma: no cover  # defensive: unreachable if auth dep is correct
        return RedirectResponse(url="/unauthorized")
    try:
        deleted = sanidad_service.delete_actuacion_sanitaria(
            client,
            actuacion_id,
            actor_user_id=_actor_user_id(user),
        )
    except InsForgeError as exc:
        log_safe(
            "sanidad.delete.backend_error",
            actuacion_id=actuacion_id,
            status_code=exc.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo contactar con el backend.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/sanidad", status_code=status.HTTP_303_SEE_OTHER
    )


# HEALTH-02 batch endpoint (issue #51) lives in ``batch_routes.py`` to
# keep each routes file under the AGENTS §21 / §28 size budgets. The
# router is registered under the same ``sanidad_router`` prefix from
# ``routes_registry.py`` so the URL contract is unchanged.
