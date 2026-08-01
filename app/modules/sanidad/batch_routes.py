"""Route layer for HEALTH-02 batch ``actuacion_sanitaria`` (issue #51).

Mirrors the ``app/modules/entradas/batch_routes.py`` style: routes are
pure HTTP / auth / template glue. All data access delegates to
``app.modules.sanidad.batch_service`` (the CTE-driven atomic commit)
and ``app.modules.sanidad.queries`` (the SQL builder seam per AGENTS §22).

The split between this file and ``routes.py`` is intentional: HEALTH-01
CRUD (``routes.py``) and HEALTH-02 batch (``batch_routes.py``) operate
on the same ``actuacion_sanitaria`` table but have distinct concerns
(single-row vs N-row, redirect-to-detail vs render preview). Keeping
them in separate files keeps each module under the AGENTS §21 (700-line
module budget) and §28 (50-line handler budget) constraints.

Endpoints (mounted at the same ``/sanidad`` prefix as
``sanidad.routes.router``):

- ``GET  /sanidad/batch/new``              empty 5-row batch form.
- ``POST /sanidad/actuaciones/batch``      atomic commit OR staging
                                              preview. Accepts a
                                              ``dry_run=true`` form
                                              field to render the
                                              per-record preview with
                                              no INSERT.
                                              **Requires writer rol**
                                              (issue #144).

Auth model (issue #144): ``GET`` uses ``require_authorized_user``.
``POST`` uses ``require_writer_user`` so the ``reader`` rol is
rejected with 403 BEFORE the handler runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Annotated

from fastapi import APIRouter, Depends, Form, Request, status
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
from app.modules.sanidad import batch_service as sanidad_batch_service

# Same prefix as the single-record router so ``routes_registry.py``
# combines both under one URL contract. The router is mounted once
# (via ``app.include_router``) — registering it twice would shadow
# the dynamic paths.
router = APIRouter(prefix="/sanidad", tags=["sanidad-batch"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
# The template context processors are shared with ``routes.py`` so the
# CSRF token + base template render identically across single-record
# and batch forms.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
    ],
)


# --- column contract (single source of truth per §4) --------------------


#: Form-field names that map 1:1 to the actucacion write columns
#: declared in ``sanidad.queries.BATCH_WRITE_COLUMNS``. The order
#: matches the CTE's ``unnest(...) AS t(...)`` tuple so a typo here
#: silently mis-binds columns; keep them aligned.
BATCH_FORM_FIELDS: tuple[str, ...] = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "tipo_actuacion_id",
    "veterinario",
    "observaciones",
    "material_utilizado",
)


#: Issue #51 acceptance: "Batch de 5+ actuaciones". Mirrors the legacy
#: ``FormFichasSanitariasAsuntoAltaMultiple`` UX which opens with five
#: blank rows. Below this threshold, the route 422s with a Spanish
#: operator-facing message — the SERVICE layer (not the route) accepts
#: any N>=1 because programmatic callers (CSV imports, sync jobs) may
#: need smaller batches.
BATCH_MIN_RECORDS: int = 5


# --- helpers (single source of truth, not route handlers) ---------------


#: ``_opt`` is the canonical normalisation helper from
#: ``app.core.forms``. Reusing it here avoids re-introducing the
#: duplicate-helper drift that Detector 10 (rule §25) tracks; the
#: ``BASELINE_DUPLICATE_HELPERS`` watch-list covers the legacy copies
#: in older modules, and new code MUST use the shared form helper.
#: See issue #227 for the broader consolidation work.

def _parse_batch_records(
    raw_rows: list[tuple[str | None, ...]],
) -> list[dict[str, Any]]:
    """Convert the form's per-row repeated fields into service records.

    Rows with all-blank fields are dropped (mirrors
    ``entradas/batch_routes.py::_parse_form_records``) so a partially-
    filled form does not produce ghost records. Each remaining row
    becomes a ``dict`` keyed by ``BATCH_FORM_FIELDS`` whose values
    pass through ``_opt`` so blank fields become ``None``.
    """
    records: list[dict[str, Any]] = []
    for row in raw_rows:
        if row is None:
            continue
        record = {
            field: _opt(row[i]) for i, field in enumerate(BATCH_FORM_FIELDS)
        }
        if any(record.values()):
            records.append(record)
    return records


def _actor_user_id(user: AuthenticatedUser) -> str | None:
    """Same shape as ``sanidad.routes._actor_user_id`` — extractor for
    audit logs. Local private mirror for the same reason as ``_opt``.
    """
    if isinstance(user, dict):
        uid = user.get("user_id")
        return str(uid) if uid is not None else None
    return None


def _render_batch_preview(
    request: Request,
    user: AuthenticatedUser,
    records: list[dict[str, Any]],
    *,
    preview: sanidad_batch_service.BatchPreview | None = None,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
):
    """Render the batch preview template with the per-row status envelope.

    ``preview`` is ``None`` only on the GET ``/sanidad/batch/new`` flow
    (no records yet). Otherwise it carries the per-record status so
    the template can paint the OK/error badges; ``records`` is the
    input echo so the form fields stay visible after re-render.
    """
    return _templates.TemplateResponse(
        request=request,
        name="sanidad/batch_preview.html",
        context={
            "user": user,
            "preview": preview,
            "records": records,
            "error": error,
        },
        status_code=status_code,
    )


def _preview_from_validation_error(
    records: list[dict[str, Any]],
    exc: sanidad_batch_service.BatchValidationError,
) -> sanidad_batch_service.BatchPreview:
    """Project the ``BatchValidationError`` into a preview envelope.

    The exception carries ``failed_indices`` + ``reasons``; the
    preview template wants a per-row ``BatchItem`` tuple. Building the
    envelope here keeps the route handler thin (rule §28).
    """
    failed = set(exc.failed_indices)
    return sanidad_batch_service.BatchPreview(
        dry_run=False,
        ok_count=len(records) - len(failed),
        error_count=len(failed),
        items=tuple(
            sanidad_batch_service.BatchItem(
                index=idx,
                status="ok" if idx not in failed else "error",
                reason=exc.reasons.get(idx),
            )
            for idx in range(len(records))
        ),
    )


# --- new (form) ---------------------------------------------------------


@router.get("/batch/new", response_class=HTMLResponse)
def new_batch_actuaciones_form(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.READ_SALUD))],
):
    """Render the empty batch form with ``BATCH_MIN_RECORDS`` blank rows.

    The preview template (``batch_preview.html``) serves both the empty
    form state (``preview=None``) and the post-submit state, so we
    only need one template per flow. This handler is GET-only — the
    write path lives at ``POST /sanidad/actuaciones/batch``.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    blank_rows = [
        {field: "" for field in BATCH_FORM_FIELDS}
        for _ in range(BATCH_MIN_RECORDS)
    ]
    return _render_batch_preview(request, user, blank_rows)


# --- batch (write) ------------------------------------------------------


@router.post("/actuaciones/batch", response_class=HTMLResponse)
def batch_actuaciones_view(
    request: Request,
    dry_run: Annotated[str | None, Form()] = None,
    animal_id: Annotated[list[str], Form()] = [],
    voluntario_id: Annotated[list[str], Form()] = [],
    fecha: Annotated[list[str], Form()] = [],
    tipo_actuacion_id: Annotated[list[str], Form()] = [],
    veterinario: Annotated[list[str], Form()] = [],
    observaciones: Annotated[list[str], Form()] = [],
    material_utilizado: Annotated[list[str], Form()] = [],
    user: Annotated[AuthenticatedUser, Depends(require_permission(Permission.WRITE_SALUD))] = None,
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)] = None,
):
    """HEALTH-02 batch endpoint: staging preview OR atomic commit.

    Thin handler: full orchestration lives in :func:`_do_batch_view`
    so this stays under the rule-§28 50-line handler budget. The
    handler exists at the API edge ONLY for FastAPI's parameter
    binding — every line of HTTP plumbing lives in the helper.
    """
    return _do_batch_view(
        request, user, client, dry_run,
        animal_id, voluntario_id, fecha,
        tipo_actuacion_id, veterinario, observaciones,
        material_utilizado,
    )


def _do_batch_view(
    request: Request,
    user: AuthenticatedUser,
    client: InsForgeClient,
    dry_run: str | None,
    animal_id: list[str],
    voluntario_id: list[str],
    fecha: list[str],
    tipo_actuacion_id: list[str],
    veterinario: list[str],
    observaciones: list[str],
    material_utilizado: list[str],
):
    """Orchestrate the batch POST — see ``batch_actuaciones_view``.

    Routes through ``sanidad_batch_service``: the service owns the
    CTE-driven atomicity guarantee (CRITICAL-1, ``bool_and`` gate in
    ``sanidad.queries``). This function only does HTTP plumbing —
    auth guard (writer rol, issue #144), form parsing, dispatch to
    preview vs commit, success-vs-failure routing.

    The ``dry_run`` form field accepts the truthy strings ``"1"``,
    ``"true"``, ``"yes"`` (case-insensitive); ``None`` and the empty
    string both count as a real commit. Other forms of truthy input
    are not honoured so a typo from the operator doesn't accidentally
    stage instead of commit.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    records = _parse_batch_records(
        list(
            zip(
                animal_id, voluntario_id, fecha,
                tipo_actuacion_id, veterinario, observaciones,
                material_utilizado, strict=False,
            )
        )
    )
    if len(records) < BATCH_MIN_RECORDS:
        return _render_batch_preview(
            request, user, records,
            error=f"Añade al menos {BATCH_MIN_RECORDS} registros al lote "
            f"(has enviado {len(records)}).",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    is_dry_run = (dry_run or "").lower() in ("1", "true", "yes")
    if is_dry_run:
        preview = sanidad_batch_service.preview_batch(client, records)
        return _render_batch_preview(request, user, records, preview=preview)

    try:
        sanidad_batch_service.commit_batch(
            client, records, actor_user_id=_actor_user_id(user)
        )
    except sanidad_batch_service.BatchValidationError as exc:
        return _render_batch_preview(
            request, user, records,
            preview=_preview_from_validation_error(records, exc),
            error=str(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except InsForgeError as exc:
        log_safe(
            "sanidad.batch.backend_error",
            record_count=len(records),
            status_code=exc.status_code,
        )
        return _render_batch_preview(
            request, user, records,
            error="No se pudo contactar con el backend. Inténtalo de nuevo "
            "en unos minutos.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return RedirectResponse(
        url="/sanidad", status_code=status.HTTP_303_SEE_OTHER
    )
