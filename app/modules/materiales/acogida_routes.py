"""Per-estancia junction routes for FOSTER-04 (#46) materiales.

PR C scope: the per-estancia junction routes that wire the
``estancia_materiales`` table into the operator's UI. The catalog
routes live in ``app.modules.materiales.routes`` (PR B); this
sub-router is mounted alongside it by ``app/main.py`` so the path
namespace ``/acogidas`` stays contiguous with the parent
``acogidas_router``.

Endpoints (mounted WITHOUT a prefix so the handler URLs are absolute):

- ``GET  /acogidas/{estancia_id}/materiales``              list the
  assigned materials for this stay; ``require_authorized_user``
  (any reader+ can view).
- ``POST /acogidas/{estancia_id}/materiales``              assign
  a material to this stay; ``require_writer_user``; 303 to the
  per-stay list; 422 on inactive material / closed stay;
  409 on duplicate active assignment (translates
  ``MaterialConflictError``).
- ``POST /acogidas/{estancia_id}/materiales/{mid}/delete``  soft-delete
  the junction row; ``require_writer_user``; 303 to the per-stay
  list; 404 when the row was missing or already inactive.

RBAC (REQ-FOSTER-04-03 + issue #144):

- ``GET`` routes use ``require_authorized_user`` (any reader+ can view).
- ``POST`` routes use ``require_writer_user`` (writers + developers +
  key_user). This is enforced at the dep layer — the ``reader`` test
  in ``tests/test_materiales_routes.py`` atom 13 sees 403 BEFORE the
  handler runs.

Same patterns as the catalog routes (PR B):

- Routes own NO SQL — every data access goes through
  ``app.modules.materiales.service`` (AGENTS.md §1).
- CSRF token is auto-injected via ``csrf_token_context_processor``
  (AGENTS.md §10); the writer-only assign form emits
  ``{{ csrf_token }}`` as a hidden input.
- All handlers call ``return_early_if_response(user)`` first as
  defense in depth (the auth middleware already bounces anonymous
  visitors to ``/login``).

The spec accepts a value-validation surface (Scenario 3 + Scenario 8
in spec #15894): the service's ``assign_material_to_estancia``
validates the estancia is open / active and the material is active
BEFORE the INSERT; a failed validation raises ``ValueError`` which
the route layer maps to 422 with an HTML re-render of the per-stay
list (operator input preserved). The catalog precedent
(``MaterialConflictError`` -> 409 with the Spanish actionable
message) is mirrored on the duplicate-assignment path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

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
from app.core.forms import optional_value as _opt
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.modules.materiales import estancia_material_service
from app.modules.materiales import service as materiales_service

# Prefix intentionally omitted (the handler URLs are absolute
# ``/acogidas/{id}/materiales``) — adding a prefix here would
# conflict with the parent ``acogidas_router`` mounted by
# ``app/main.py``. The router is tagged ``materiales-junction`` so
# the OpenAPI doc groups the per-stay material endpoints next to
# the catalog endpoints without leaking the implementation
# detail into the URL namespace.
router = APIRouter(tags=["materiales-junction"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
    ],
)


# --- helpers --------------------------------------------------------------


def _cantidad_or_default(raw: str | None) -> int:
    """Parse the ``cantidad`` form field with a default of 1.

    Defense in depth on top of the DB CHECK constraint
    (``cantidad > 0``) — an operator who deletes the value and
    types a letter sees a clear Spanish 422 instead of an opaque
    PostgreSQL constraint violation. Mirrors the
    ``_validate_capacidad`` precedent in
    ``app/modules/foster/service.py``.
    """
    cleaned = (raw or "1").strip()
    try:
        value = int(cleaned)
    except ValueError as exc:
        raise ValueError(
            "cantidad debe ser un entero positivo (>= 1)"
        ) from exc
    if value < 1:
        raise ValueError("cantidad debe ser un entero positivo (>= 1)")
    return value


def _render_per_stay_list(  # noqa: PLR0913  # non-route helper; 7 args needed to populate the per-stay template context
    request: Request,
    user: AuthenticatedUser,
    estancia_id: str,
    *,
    assigned: list[materiales_service.EstanciaMaterial],
    catalog: list[materiales_service.Material],
    error: str | None,
    status_code: int = status.HTTP_200_OK,
):
    """Render ``acogidas/materiales.html`` with a fixed context.

    Centralizes the template-name + context keys so each handler
    declares only the form payload + error string. Mirrors the
    ``_render_form`` precedent in
    ``app/modules/materiales/routes.py`` and the foster module.

    The catalog list is passed for the writer-only ``material_id``
    dropdown — only active materials are eligible for assignment
    (the service-side ``_validate_material_active`` rejects
    inactive materials with 422 anyway, so the dropdown only shows
    ``activos_solo=True`` rows).

    CRITICAL-1 (jd-judge-a, PR #171): the per-stay table needs to
    render the material's natural-key trio (material / tamano /
    color), NOT the FK UUID ``row.material_id``. We pre-build a
    ``material_lookup`` dict keyed by ``Material.id`` so the template
    can resolve each junction row's FK in O(1) without a second
    SELECT per row. The lookup is only used to enrich the rendering;
    the writer-only dropdown keeps iterating the original ``catalog``
    list (the dropdown already renders the same trio via ``mat.material
    — mat.tamano — mat.color``).

    On a 409 (duplicate active assignment) or a 422 (inactive
    material / closed estancia), the form-data is preserved by
    re-rendering through this helper.
    """
    material_lookup: dict[str, materiales_service.Material] = {
        m.id: m for m in catalog
    }
    return _templates.TemplateResponse(
        request=request,
        name="acogidas/materiales.html",
        context={
            "user": user,
            "estancia_id": estancia_id,
            "assigned": assigned,
            "catalog": catalog,
            "material_lookup": material_lookup,
            "error": error,
        },
        status_code=status_code,
    )


# --- GET /acogidas/{id}/materiales ---------------------------------------


@router.get("/acogidas/{estancia_id}/materiales", response_class=HTMLResponse)
def list_estancia_materiales_view(
    estancia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_authorized_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Per-stay junction list.

    Renders ``app/templates/acogidas/materiales.html`` with the
    assigned materials ordered by ``fecha_alta DESC`` (the service
    applies the ordering in SQL) and the catalog of active materials
    for the writer-only assign dropdown.

    The page is reachable by any authorized user; the assign +
    remove forms are gated by ``user.rol in (writer, developer,
    key_user)`` in the template (mirrors the RBAC pattern used by
    the catalog list at ``app/templates/materiales/list.html``).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    assigned = estancia_material_service.list_materials_for_estancia(
        client, estancia_id, activos_solo=True
    )
    catalog = materiales_service.list_materials(client, activos_solo=True)
    return _render_per_stay_list(
        request,
        user,
        estancia_id,
        assigned=assigned,
        catalog=catalog,
        error=None,
    )


# --- POST /acogidas/{id}/materiales --------------------------------------


@router.post("/acogidas/{estancia_id}/materiales", response_class=HTMLResponse)
def assign_material_to_estancia_view(  # noqa: PLR0913  # 2 Form fields + 5 fixed deps; form model would add noise
    estancia_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_writer_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    material_id: Annotated[str, Form()],
    cantidad: Annotated[str, Form()] = "1",
    notas: Annotated[str | None, Form()] = None,
):
    """Assign a material to this stay.

    Status-code contract (spec #15894 Scenarios 3, 4, 8):

    - 303 to ``/acogidas/{id}/materiales`` on success.
    - 422 HTML re-render of the per-stay list when the service
      raises ``ValueError`` — covers Scenario 8 (inactive
      material) and Q5 (closed / soft-deleted stay). Operator
      input is preserved so they can fix and retry.
    - 409 HTML re-render with the Spanish "ese material ya esta
      asignado a esta estancia" message on
      ``MaterialConflictError``. Mirrors the catalog precedent at
      ``app/modules/materiales/routes.py::create_material_view``.

    Cardinality: this is a mutation handler. The service-level
    validation (closed stay / inactive material) runs BEFORE the
    INSERT, so a failed validation never writes a junction row;
    successful POSTs add exactly one row.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        cantidad_int = _cantidad_or_default(cantidad)
    except ValueError as exc:
        assigned = estancia_material_service.list_materials_for_estancia(
            client, estancia_id, activos_solo=True
        )
        catalog = materiales_service.list_materials(client, activos_solo=True)
        return _render_per_stay_list(
            request,
            user,
            estancia_id,
            assigned=assigned,
            catalog=catalog,
            error=str(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    notas_clean = _opt(notas)
    try:
        estancia_material_service.assign_material_to_estancia(
            client,
            estancia_id,
            material_id,
            cantidad=cantidad_int,
            notas=notas_clean,
        )
    except materiales_service.MaterialConflictError as exc:
        assigned = estancia_material_service.list_materials_for_estancia(
            client, estancia_id, activos_solo=True
        )
        catalog = materiales_service.list_materials(client, activos_solo=True)
        return _render_per_stay_list(
            request,
            user,
            estancia_id,
            assigned=assigned,
            catalog=catalog,
            error=f"ese material ya esta asignado a esta estancia: {exc}",
            status_code=status.HTTP_409_CONFLICT,
        )
    except ValueError as exc:
        assigned = estancia_material_service.list_materials_for_estancia(
            client, estancia_id, activos_solo=True
        )
        catalog = materiales_service.list_materials(client, activos_solo=True)
        return _render_per_stay_list(
            request,
            user,
            estancia_id,
            assigned=assigned,
            catalog=catalog,
            error=str(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        url=f"/acogidas/{estancia_id}/materiales",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- POST /acogidas/{id}/materiales/{mid}/delete -------------------------


@router.post(
    "/acogidas/{estancia_id}/materiales/{junction_id}/delete",
    response_class=HTMLResponse,
)
def remove_material_from_estancia_view(
    estancia_id: str,
    junction_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_writer_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    """Soft-delete a single junction row.

    Returns 303 to ``/acogidas/{id}/materiales`` on success
    (service True). Returns 404 when the service signals the row
    was missing OR already inactive — the service folds both into
    a single ``False`` sentinel (same shape as
    ``deactivate_material`` on the catalog).

    Idempotency: a SECOND POST against the same junction id is
    safe — the service returns ``False`` on the second call and
    the handler returns 404 instead of redirecting. The reverse-
    redirect-to-self pattern is the standard 404 contract (issue
    #144, foster ``test_delete_casa_acogida_returns_404_when_id_missing``).
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    if not estancia_material_service.remove_material_from_estancia(
        client, junction_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url=f"/acogidas/{estancia_id}/materiales",
        status_code=status.HTTP_303_SEE_OTHER,
    )
