"""Route layer for FOSTER-02 estancias de acogida (CRUD).

Mirrors ``app/modules/foster/routes.py`` (FOSTER-01) and
``app/modules/entradas/routes.py`` (INTAKE-01): routes are pure HTTP /
auth / template glue. All data access delegates to
``app.modules.acogidas.service``.

Endpoints (mounted at ``/acogidas`` by ``app/main.py``):

- ``GET  /acogidas``                       list of stays (active + closed)
                                                with optional ``?activas_solo=1``
                                                filter.
- ``GET  /acogidas/new``                   empty form.
- ``POST /acogidas``                       create; redirect to detail on
                                                success.
- ``GET  /acogidas/{id}``                  detail view with duration +
                                                close/delete buttons.
- ``GET  /acogidas/{id}/edit``             edit form prefilled.
- ``POST /acogidas/{id}/update``           update.
- ``POST /acogidas/{id}/close``            close stay (fecha_final=today).
- ``POST /acogidas/{id}/delete``           soft-delete.
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
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.middleware import base_template_context_processor
from app.core.rbac import Permission, require_permission
from app.modules.acogidas import service as acogidas_service
from app.modules.foster import assignment_service

router = APIRouter(prefix="/acogidas", tags=["foster"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


_FORM_FIELDS = (
    "animal_id",
    "casa_acogida_id",
    "voluntario_acogida_id",
    "voluntario_seguimiento1_id",
    "voluntario_seguimiento2_id",
    "voluntario_sanitario_id",
    "fecha_inicio",
    "fecha_final",
    "entrada_origen_id",
    "direccion",
    "telefono",
    "observaciones",
)


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _enforce_species_gate(
    client: InsForgeClient,
    animal_id: str,
    casa_acogida_id: str | None,
) -> str | None:
    """Run the FOSTER-03 species gate before persisting a stay.

    Returns the gate's rejection reason (a Spanish message ready for the
    form's ``error`` banner) when the species mismatch would block the
    assignment; ``None`` when the form is compatible (admit /
    admit_with_warning) OR when the form doesn't carry a
    ``casa_acogida_id`` (legacy compat — FOSTER-02 allowed estancias
    without a casa and that path is preserved).

    FOSTER-03 (#45) close bypass P0: previously the species gate only
    fired from ``/casas-acogida/{id}/asignar`` (the FOSTER-03 evaluate
    form). The legacy FOSTER-02 POST /acogidas accepted any
    ``casa_acogida_id`` without consulting the gate, so an operator
    could create a felino+canina-only estancia with one curl. This
    helper closes the bypass from the route layer without touching
    ``acogidas.service.create_acogida`` (D-GC-05: gate stays as an
    orthogonal module — service owns no SQL gate, route enforces).

    The helper delegates to
    :func:`app.modules.foster.assignment.evaluate_assignment`, which
    raises ``ValueError`` for missing/inactive animal or casa. Those
    errors are NOT translated here — they propagate so the calling
    route's ``try/except ValueError`` renders them as 422 (consistent
    with how the FOSTER-03 evaluate form already handles them).
    """
    if not casa_acogida_id:
        return None  # legacy compat — estancia without casa skips the gate
    decision = assignment_service.evaluate_assignment(
        client, animal_id, casa_acogida_id
    )
    if decision.decision == "block":
        return decision.reason
    return None


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    return {key: _opt(form.get(key)) for key in _FORM_FIELDS}


def _acogida_to_form_data(acogida: acogidas_service.Acogida) -> dict[str, Any]:
    return {
        "animal_id": acogida.animal_id,
        "casa_acogida_id": acogida.casa_acogida_id or "",
        "voluntario_acogida_id": acogida.voluntario_acogida_id or "",
        "voluntario_seguimiento1_id": acogida.voluntario_seguimiento1_id or "",
        "voluntario_seguimiento2_id": acogida.voluntario_seguimiento2_id or "",
        "voluntario_sanitario_id": acogida.voluntario_sanitario_id or "",
        "fecha_inicio": acogida.fecha_inicio,
        "fecha_final": acogida.fecha_final or "",
        "entrada_origen_id": acogida.entrada_origen_id or "",
        "direccion": acogida.direccion or "",
        "telefono": acogida.telefono or "",
        "observaciones": acogida.observaciones or "",
    }


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
        name="acogidas/form.html",
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
def list_acogidas_view(
    request: Request,
    activas_solo: int | None = None,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """List stays; ``?activas_solo=1`` filters to open stays."""
    if (early := return_early_if_response(user)) is not None:
        return early
    solo = bool(activas_solo)
    acogidas = acogidas_service.list_acogidas(client, activas_solo=solo)
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/list.html",
        context={
            "user": user,
            "acogidas": acogidas,
            "activas_solo": solo,
        },
    )


# --- new (form) -----------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_acogida_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_ACOGIDAS)),
):
    """Render an empty create form."""
    if (early := return_early_if_response(user)) is not None:
        return early
    return _render_form(request, user, {}, None, "/acogidas")


# --- create (submit) ------------------------------------------------------


@router.post("", response_class=HTMLResponse)
def create_acogida_view(
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    override_id: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a new estancia; redirect to detail on success, re-render form on validation error.

    Issue #142: ``override_id`` is the (optional) hidden form field
    threaded from ``POST /casas-acogida/{id}/asignar`` when the gate
    returns ``admit_with_warning`` and the operator confirmed the
    override. ``create_acogida`` uses it to UPDATE the
    ``foster_capacity_overrides.estancia_id`` column so the audit
    log row is no longer orphaned. An empty string is treated the
    same as absent.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )
    # Issue #142: thread override_id through to the service so it can
    # link the foster_capacity_overrides row.
    if override_id is not None and override_id.strip():
        form_data["override_id"] = override_id.strip()
    # FOSTER-03 (#45) close bypass P0: the species gate must run before
    # the INSERT. The helper returns the rejection reason (Spanish
    # message) when the gate would block the assignment; we render the
    # same form with 422. Capacity-warning outcomes (admit_with_warning)
    # pass through — the operator confirmed the override at /asignar
    # (FOSTER-03 explicit flow), and the stay record itself does not
    # require a motivo (only the audit log of the override does, and
    # that was already recorded in /asignar before the redirect).
    gate_error = _enforce_species_gate(
        client, animal_id, form_data.get("casa_acogida_id")
    )
    if gate_error:
        return _render_form(
            request,
            user,
            form_data,
            gate_error,
            "/acogidas",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    try:
        acogida = acogidas_service.create_acogida(client, form_data)
    except InsForgeError as exc:
        # Issue #139 P1 #4 (TOCTOU mitigation): _validate_references runs
        # SELECTs before the INSERT; a concurrent deactivate between the
        # SELECT and the INSERT can still produce a PostgreSQL FK
        # violation (PostgREST 23503 / "violates foreign key
        # constraint"). The service raises ``InsForgeError`` on a 4xx
        # response; we translate it to a 422 with the operator's form
        # input preserved, so the failure surfaces as an actionable
        # form error instead of a 500.
        return _render_form(
            request,
            user,
            form_data,
            _format_persisted_error(exc, "estancia de acogida"),
            "/acogidas",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            "/acogidas",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/acogidas/{acogida.id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- detail ---------------------------------------------------------------


@router.get("/{acogida_id}", response_class=HTMLResponse)
def acogida_detail(
    acogida_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the stay detail view with computed duration + active state."""
    if (early := return_early_if_response(user)) is not None:
        return early
    acogida = acogidas_service.get_acogida_by_id(client, acogida_id)
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    duracion = acogidas_service.compute_duracion(acogida)
    active = acogidas_service.is_active(acogida)
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/detail.html",
        context={
            "user": user,
            "acogida": acogida,
            "duracion": duracion,
            "active": active,
        },
    )


# --- edit (form) ---------------------------------------------------------


@router.get("/{acogida_id}/edit", response_class=HTMLResponse)
def edit_acogida_form(
    acogida_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.READ_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the edit form prefilled from the current stay row."""
    if (early := return_early_if_response(user)) is not None:
        return early
    acogida = acogidas_service.get_acogida_by_id(client, acogida_id)
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_form(
        request,
        user,
        _acogida_to_form_data(acogida),
        None,
        f"/acogidas/{acogida_id}/update",
    )


# --- update (submit) ------------------------------------------------------


@router.post("/{acogida_id}/update", response_class=HTMLResponse)
def update_acogida_view(
    acogida_id: str,
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Apply form edits; redirect to detail on success, re-render on validation error."""
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )
    # FOSTER-03 (#45) close bypass P0: same gate as in create_acogida_view.
    # We always gate the NEW (incoming) form values. If the operator
    # moves a stay from casa X to casa Y, gate (animal_id, Y). If they
    # keep the same casa, the gate evaluates the same combo as create
    # did when the stay was first opened — cheap one-shot SQL re-check
    # in exchange for not having to load the existing row to compare
    # (avoids a SELECT-then-UPDATE TOCTOU pattern).
    gate_error = _enforce_species_gate(
        client, animal_id, form_data.get("casa_acogida_id")
    )
    if gate_error:
        return _render_form(
            request,
            user,
            form_data,
            gate_error,
            f"/acogidas/{acogida_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    try:
        acogida = acogidas_service.update_acogida(client, acogida_id, form_data)
    except InsForgeError as exc:
        # Issue #139 P1 #4 (TOCTOU mitigation): see create_acogida_view.
        # UPDATE path can also hit a concurrent FK violation between
        # ``_validate_references`` and the UPDATE.
        return _render_form(
            request,
            user,
            form_data,
            _format_persisted_error(exc, "estancia de acogida"),
            f"/acogidas/{acogida_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except ValueError as exc:
        return _render_form(
            request,
            user,
            form_data,
            str(exc),
            f"/acogidas/{acogida_id}/update",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if acogida is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/acogidas/{acogida_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- close (end of stay, lifecycle event) --------------------------------


@router.post("/{acogida_id}/close", response_class=HTMLResponse)
def close_acogida_view(
    acogida_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Close the stay: ``fecha_final = current_date``, ``activo`` stays true.

    D-EST-04: closing is a lifecycle event (the animal returns to the
    shelter or moves to adoption), NOT a soft-delete. The stay row
    remains visible in the listing with ``fecha_final`` populated.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if acogidas_service.close_acogida(client, acogida_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/acogidas/{acogida_id}", status_code=status.HTTP_303_SEE_OTHER
    )


# --- delete (soft) --------------------------------------------------------


@router.post("/{acogida_id}/delete", response_class=HTMLResponse)
def delete_acogida_view(
    acogida_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_permission(Permission.WRITE_ACOGIDAS)),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Soft-delete the stay: ``activo = false`` + ``fecha_baja = now()``.

    Redirects to the list view on success. Returns 404 if the service
    reports the row was missing or already inactive.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not acogidas_service.delete_acogida(client, acogida_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/acogidas", status_code=status.HTTP_303_SEE_OTHER
    )


# --- error formatting helpers ---------------------------------------------


def _format_persisted_error(exc: InsForgeError, entity_label: str) -> str:
    """Turn an ``InsForgeError`` into a Spanish-friendly 422 message.

    Issue #139 P1 #4 (TOCTOU mitigation): the service catches a 4xx
    ``InsForgeError`` and propagates it as-is. The route translates the
    opaque InsForge body into an operator-facing message. PostgreSQL FK
    violations arrive as PostgREST 400 with a body that mentions the
    constraint name (e.g. ``acogidas_animal_id_fkey``); for any other
    shape we fall back to the raw body so the operator can still
    diagnose.
    """
    body_text = str(exc.body).lower() if exc.body is not None else ""
    if "foreign key" in body_text or "violates" in body_text:
        return (
            f"No se pudo guardar la {entity_label}: una referencia "
            f"extranjera (animal, casa, voluntario o entrada) dejó de "
            f"ser válida entre la validación y el guardado. Revisa los "
            f"identificadores e inténtalo de nuevo."
        )
    return f"No se pudo guardar la {entity_label}: {exc}"
