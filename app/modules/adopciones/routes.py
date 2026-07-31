"""Route layer for ADOPT-01 adopciones (CRUD).

Mirrors ``app/modules/entradas/routes.py`` and
``app/modules/foster/routes.py``: routes are pure HTTP / auth /
template glue. All data access delegates to
``app.modules.adopciones.service``.

Endpoints (mounted at ``/adopciones`` by ``app/main.py``):

- ``GET  /adopciones``                          list of active
                                                  adopciones
                                                  (with optional
                                                  ``?adoptante=``
                                                  filter).
- ``GET  /adopciones/new``                      empty form.
- ``POST /adopciones``                          create; redirect to
                                                  detail on success.
                                                  **Requires writer
                                                  rol** (issue #144).
- ``GET  /adopciones/{id}``                     detail view.
- ``GET  /adopciones/{id}/edit``                edit form prefilled.
- ``POST /adopciones/{id}/update``              update.
                                                  **Requires writer
                                                  rol** (issue #144).
- ``POST /adopciones/{id}/delete``              soft-delete.
                                                  **Requires writer
                                                  rol** (issue #144).

Auth model (issue #144): GET endpoints use ``require_authorized_user``
(read access stays open to any authorized operator). Write endpoints
(POST create / POST update / POST delete) use
``require_writer_user`` which composes on ``require_authorized_user``
and rejects the ``reader`` rol with 403 BEFORE the handler runs. This
closes the P1-3 (risk review 2026-07-04) authz gap where a reader
could previously POST / DELETE adopciones.
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
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.middleware import base_template_context_processor
from app.modules.adopciones import service as adopciones_service

router = APIRouter(prefix="/adopciones", tags=["adopciones"])

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
    "voluntario_seguimiento_id",
    "fecha_adopcion",
    "fecha_devolucion",
    "donativo_preadopcion",
    "donativo_adopcion",
    "nombre_adoptante",
    "dni_adoptante",
    "telefono_adoptante",
    "email_adoptante",
    "entrada_origen_id",
    "observaciones",
    "tipo_adopcion",
)


def _opt(value: str | None) -> str | None:
    """Strip a string or convert empty to ``None`` for optional fields.

    Mirrors ``entradas/routes.py::_opt`` and ``cesiones/routes.py::_opt``.
    Lets the operator leave optional fields blank in the form (e.g.
    ``dni_adoptante``) and have the service write NULL to the DB
    rather than an empty string.
    """
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    """Translate the raw form dict into the service's ``params`` schema.

    ``donativo_*`` are kept as strings here on purpose: the service's
    ``_optional_numeric`` raises a clean ``ValueError`` on bad input
    (the route would otherwise crash on a hand-rolled ``int()`` /
    ``float()``). Empty strings stay empty so the service treats them
    as ``None``.

    P1-2 (readability review 2026-07-04): the previous
    ``_opt_numeric`` wrapper was a redundant ``return _opt(value)``.
    Removed; the comprehension below applies ``_opt`` to every form
    field including ``donativo_preadopcion`` / ``donativo_adopcion``.
    """
    return {key: _opt(form.get(key)) for key in _FORM_FIELDS}


def _adopcion_to_form_data(
    adopcion: adopciones_service.Adopcion,
) -> dict[str, Any]:
    return {
        "animal_id": adopcion.animal_id,
        "voluntario_seguimiento_id": adopcion.voluntario_seguimiento_id or "",
        "fecha_adopcion": adopcion.fecha_adopcion,
        "fecha_devolucion": adopcion.fecha_devolucion or "",
        "donativo_preadopcion": (
            str(adopcion.donativo_preadopcion)
            if adopcion.donativo_preadopcion is not None
            else ""
        ),
        "donativo_adopcion": (
            str(adopcion.donativo_adopcion)
            if adopcion.donativo_adopcion is not None
            else ""
        ),
        "nombre_adoptante": adopcion.nombre_adoptante,
        "dni_adoptante": adopcion.dni_adoptante or "",
        "telefono_adoptante": adopcion.telefono_adoptante or "",
        "email_adoptante": adopcion.email_adoptante or "",
        "entrada_origen_id": adopcion.entrada_origen_id or "",
        "observaciones": adopcion.observaciones or "",
        "tipo_adopcion": adopcion.tipo_adopcion,
    }


def _actor_user_id(user: AuthenticatedUser) -> str | None:
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
    user: AuthenticatedUser,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    status_code: int = status.HTTP_200_OK,
):
    return _templates.TemplateResponse(
        request=request,
        name="adopciones/form.html",
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
def list_adopciones_view(
    request: Request,
    adoptante: str | None = None,
    user: AuthenticatedUser = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """List active adopciones; ``?adoptante=`` filters by name (ILIKE)."""
    if (early := return_early_if_response(user)) is not None:
        return early
    if adoptante and adoptante.strip():
        adopciones = adopciones_service.search_adopciones_by_adoptante(
            client, adoptante
        )
    else:
        adopciones = adopciones_service.list_adopciones(client)
    return _templates.TemplateResponse(
        request=request,
        name="adopciones/list.html",
        context={
            "user": user,
            "adopciones": adopciones,
            "adoptante": adoptante or "",
        },
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_adopcion_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_authorized_user),
):
    """Empty form for a new adopción."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/adopciones")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_adopcion_view(
    request: Request,
    animal_id: str = Form(...),
    voluntario_seguimiento_id: str | None = Form(None),
    fecha_adopcion: str = Form(...),
    fecha_devolucion: str | None = Form(None),
    donativo_preadopcion: str | None = Form(None),
    donativo_adopcion: str | None = Form(None),
    nombre_adoptante: str = Form(...),
    dni_adoptante: str | None = Form(None),
    telefono_adoptante: str | None = Form(None),
    email_adoptante: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    observaciones: str | None = Form(None),
    tipo_adopcion: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create an adopción; redirect to detail on success.

    P1-3 (risk review 2026-07-04): write endpoint, requires
    ``require_writer_user`` so a ``reader`` rol is rejected with 403
    BEFORE the handler runs (issue #144).

    P1-2 (risk review 2026-07-04): the try/except wraps both
    ``ValueError`` (FK / required-field / numeric coercion errors) AND
    ``InsForgeError`` (CHECK constraint violation on ``tipo_adopcion``
    surfacing as 4xx, malformed date on ``fecha_adopcion`` /
    ``fecha_devolucion`` surfacing as 4xx). Any of these now renders as
    a 422 with the operator's form input preserved, instead of leaking
    as a 500.

    P1-1 (readability review 2026-07-04): ``AdopcionConflictError`` (a
    ``ValueError`` subclass) is caught SEPARATELY so the natural-key
    UNIQUE violation renders as 409 with a Spanish-friendly message,
    not as a generic 422. Mirrors the entradas / cesiones pattern.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "voluntario_seguimiento_id": voluntario_seguimiento_id,
            "fecha_adopcion": fecha_adopcion,
            "fecha_devolucion": fecha_devolucion,
            "donativo_preadopcion": donativo_preadopcion,
            "donativo_adopcion": donativo_adopcion,
            "nombre_adoptante": nombre_adoptante,
            "dni_adoptante": dni_adoptante,
            "telefono_adoptante": telefono_adoptante,
            "email_adoptante": email_adoptante,
            "entrada_origen_id": entrada_origen_id,
            "observaciones": observaciones,
            "tipo_adopcion": tipo_adopcion,
        }
    )
    try:
        adopcion = adopciones_service.create_adopcion(
            client,
            form_data,
            actor_user_id=_actor_user_id(user),
        )
    except adopciones_service.AdopcionConflictError:
        return _render_form(
            request,
            user,
            form_data,
            "Ya existe una adopción para ese animal y fecha. "
            "Edita la existente o elimínala antes de crear otra.",
            "/adopciones",
            status.HTTP_409_CONFLICT,
        )
    except (ValueError, InsForgeError) as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar la adopción: {exc}",
            "/adopciones",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/adopciones/{adopcion.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{adopcion_id}", response_class=HTMLResponse)
def adopcion_detail(
    adopcion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Detail view; 404 when the id is missing."""
    if (early := return_early_if_response(user)) is not None:
        return early
    adopcion = adopciones_service.get_adopcion_by_id(client, adopcion_id)
    if adopcion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="adopciones/detail.html",
        context={"user": user, "adopcion": adopcion},
    )


# --- edit (form) ----------------------------------------------------------


@router.get("/{adopcion_id}/edit", response_class=HTMLResponse)
def edit_adopcion_form(
    adopcion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Edit form prefilled from the persisted row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    adopcion = adopciones_service.get_adopcion_by_id(client, adopcion_id)
    if adopcion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _adopcion_to_form_data(adopcion),
        None,
        f"/adopciones/{adopcion_id}/update",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{adopcion_id}/update", response_class=HTMLResponse)
def update_adopcion_view(
    adopcion_id: str,
    request: Request,
    animal_id: str = Form(...),
    voluntario_seguimiento_id: str | None = Form(None),
    fecha_adopcion: str = Form(...),
    fecha_devolucion: str | None = Form(None),
    donativo_preadopcion: str | None = Form(None),
    donativo_adopcion: str | None = Form(None),
    nombre_adoptante: str = Form(...),
    dni_adoptante: str | None = Form(None),
    telefono_adoptante: str | None = Form(None),
    email_adoptante: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    observaciones: str | None = Form(None),
    tipo_adopcion: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Update an existing adopción; redirect to detail on success.

    P1-3 (risk review 2026-07-04): write endpoint, requires
    ``require_writer_user``. P1-2: catches both ``ValueError`` and
    ``InsForgeError`` for a clean 422 with the operator's form input
    preserved. P1-1: ``AdopcionConflictError`` is caught separately to
    render the natural-key UNIQUE violation as 409.

    P2-1 (risk review 2026-07-04): previously only ``create_adopcion``
    translated the UNIQUE violation; now ``update_adopcion`` does the
    same so an operator editing a row to clash with an existing
    adoption gets a friendly 409 instead of a 500.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "voluntario_seguimiento_id": voluntario_seguimiento_id,
            "fecha_adopcion": fecha_adopcion,
            "fecha_devolucion": fecha_devolucion,
            "donativo_preadopcion": donativo_preadopcion,
            "donativo_adopcion": donativo_adopcion,
            "nombre_adoptante": nombre_adoptante,
            "dni_adoptante": dni_adoptante,
            "telefono_adoptante": telefono_adoptante,
            "email_adoptante": email_adoptante,
            "entrada_origen_id": entrada_origen_id,
            "observaciones": observaciones,
            "tipo_adopcion": tipo_adopcion,
        }
    )
    try:
        adopcion = adopciones_service.update_adopcion(
            client,
            adopcion_id,
            form_data,
            actor_user_id=_actor_user_id(user),
        )
    except adopciones_service.AdopcionConflictError:
        return _render_form(
            request,
            user,
            form_data,
            "Ya existe una adopción para ese animal y fecha. "
            "Edita la existente o elimínala antes de crear otra.",
            f"/adopciones/{adopcion_id}/update",
            status.HTTP_409_CONFLICT,
        )
    except (ValueError, InsForgeError) as exc:
        return _render_form(
            request,
            user,
            form_data,
            f"No se pudo guardar la adopción: {exc}",
            f"/adopciones/{adopcion_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if adopcion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/adopciones/{adopcion_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) -------------------------------------------------------


@router.post("/{adopcion_id}/delete", response_class=HTMLResponse)
def delete_adopcion_view(
    adopcion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete via ``adopciones_service.delete_adopcion``; redirect to list.

    P1-3 (risk review 2026-07-04): write endpoint, requires
    ``require_writer_user`` so a ``reader`` rol is rejected with 403.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not adopciones_service.delete_adopcion(
        client,
        adopcion_id,
        actor_user_id=_actor_user_id(user),
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/adopciones", status_code=status.HTTP_303_SEE_OTHER
    )


# --- seguimiento state transition (ADOPT-03, issue #49) --------------------


@router.patch(
    "/{adopcion_id}/seguimiento",
    response_class=HTMLResponse,
    tags=["adopciones"],
)
def seguimiento_transition_view(
    adopcion_id: str,
    request: Request,
    action: str = Form(...),
    documento_url: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Transition the seguimiento estado for an adopcion.

    Body (form): ``action`` is required (``marcar_entregado``,
    ``anexar_documento``, ``completar``). ``documento_url`` is required
    only for ``anexar_documento``.

    Returns 409 Conflict when the transition is invalid for the current
    estado. Returns 404 when the adopcion does not exist.
    Returns 303 redirect to the detail view on success.
    """
    if (early := return_early_if_response(user)) is not None:
        return early

    outcome = adopciones_service.transition_seguimiento_for_route(
        client,
        adopcion_id=adopcion_id,
        action=action,
        operador_user_id=_actor_user_id(user) or "unknown",
        documento_url=documento_url,
    )

    if isinstance(outcome, adopciones_service._SeguirTransitionError):
        return _render_form(
            request,
            user,
            {},
            outcome.message,
            f"/adopciones/{adopcion_id}",
            outcome.status_code,
        )

    return RedirectResponse(
        url=f"/adopciones/{adopcion_id}", status_code=status.HTTP_303_SEE_OTHER
    )
