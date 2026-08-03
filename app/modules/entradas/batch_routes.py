"""Route layer for INTAKE-02 batch entradas (Entradas Múltiples).

Mirrors the ``app/modules/entradas/routes.py`` style: routes handle
HTTP, auth guards, form parsing, redirects, and template rendering.
All data access delegates to ``batch_service``.

Endpoints (mounted at ``/entradas/batch`` by ``app/main.py``):

- ``GET  /entradas/batch/new``             form to capture N records.
- ``POST /entradas/batch``                  stage records; redirect to
                                             preview or back to form on
                                             cross-batch duplicate.
- ``GET  /entradas/batch/{batch_id}``       preview page (status per record).
- ``POST /entradas/batch/{batch_id}/commit``atomic copy staging -> entradas.
- ``POST /entradas/batch/{batch_id}/cancel`` cancel staging without commit.

Cancel uses ``POST`` (not ``DELETE``) because the HTML form does not
support DELETE natively and the project prefers an explicit
``/cancel`` route over an ``_method`` override.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    require_authorized_user,
    require_writer_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient
from app.core.middleware import base_template_context_processor
from app.modules.entradas import batch_service

router = APIRouter(prefix="/entradas/batch", tags=["entradas-batch"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor, base_template_context_processor],
)


_BLANK_ROW = {
    "animal_id": "",
    "voluntario_entrada_id": "",
    "fecha_entrada": "",
    "origen": "",
    "motivo": "",
    "observaciones": "",
}


def _opt(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _build_initial_rows(num_rows: int = 5) -> list[dict[str, Any]]:
    """Return ``num_rows`` blank rows for the form template."""
    return [{**_BLANK_ROW} for _ in range(num_rows)]


def _form_data_to_params(form: dict[str, Any]) -> dict[str, Any]:
    return {
        "animal_id": _opt(form.get("animal_id")),
        "voluntario_entrada_id": _opt(form.get("voluntario_entrada_id")),
        "fecha_entrada": _opt(form.get("fecha_entrada")),
        "origen": _opt(form.get("origen")),
        "motivo": _opt(form.get("motivo")),
        "observaciones": _opt(form.get("observaciones")),
    }


def _parse_form_records(form_values: list[Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """Parse the dynamic rows posted from ``batch_new.html``.

    ``form_values`` is the list of values returned by FastAPI's
    ``Form(...)`` repeatable parameter mechanism; each entry is a
    dict of fields for one row. Rows with all-blank fields are dropped
    so a partially-filled form does not produce ghost records.
    """
    records: list[dict[str, Any]] = []
    for entry in form_values:
        if entry is None:
            continue
        if not isinstance(entry, dict):
            entry = dict(entry)
        params = _form_data_to_params(entry)
        if not any(params.values()):
            continue
        records.append(params)
    return records


@router.get("/new", response_class=HTMLResponse)
def new_batch_form(
    request: Request,
    user: Annotated[Response | dict, Depends(require_authorized_user)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="entradas/batch_new.html",
        context={
            "user": user,
            "rows": _build_initial_rows(5),
            "error": None,
        },
    )


@router.post("", response_class=HTMLResponse)
def stage_batch_view(
    request: Request,
    user: Annotated[Response | dict, Depends(require_writer_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
    animal_id: Annotated[list[str] | None, Form()] = None,
    voluntario_entrada_id: Annotated[list[str] | None, Form()] = None,
    fecha_entrada: Annotated[list[str] | None, Form()] = None,
    origen: Annotated[list[str] | None, Form()] = None,
    motivo: Annotated[list[str] | None, Form()] = None,
    observaciones: Annotated[list[str] | None, Form()] = None,
):
    if (early := return_early_if_response(user)) is not None:
        return early

    rows_input = list(
        zip(
            animal_id or [],
            voluntario_entrada_id or [],
            fecha_entrada or [],
            origen or [],
            motivo or [],
            observaciones or [],
            strict=False,
        )
    )
    raw_records = [
        {
            "animal_id": a,
            "voluntario_entrada_id": v,
            "fecha_entrada": f,
            "origen": o,
            "motivo": m,
            "observaciones": obs,
        }
        for a, v, f, o, m, obs in rows_input
    ]
    records = [r for r in (_form_data_to_params(rec) for rec in raw_records) if any(r.values())]

    if not records:
        return _templates.TemplateResponse(
            request=request,
            name="entradas/batch_new.html",
            context={
                "user": user,
                "rows": _build_initial_rows(max(5, len(raw_records))),
                "error": "Añade al menos una entrada antes de previsualizar.",
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    try:
        staging = batch_service.stage_batch(client, records)
    except batch_service.BatchValidationError as exc:
        # Re-render the form with the operator's input preserved so they
        # can fix the duplicated row without retyping everything.
        preserved_rows = []
        for entry in raw_records:
            row = dict(_BLANK_ROW)
            for key, value in entry.items():
                if value is not None:
                    row[key] = value
            preserved_rows.append(row)
        return _templates.TemplateResponse(
            request=request,
            name="entradas/batch_new.html",
            context={
                "user": user,
                "rows": preserved_rows or _build_initial_rows(5),
                "error": str(exc),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return RedirectResponse(
        url=f"/entradas/batch/{staging.batch_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{batch_id}", response_class=HTMLResponse)
def batch_preview(
    batch_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_authorized_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    staging = batch_service.get_batch(client, batch_id)
    if staging is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _templates.TemplateResponse(
        request=request,
        name="entradas/batch_preview.html",
        context={
            "user": user,
            "batch": staging,
        },
    )


@router.post("/{batch_id}/commit", response_class=HTMLResponse)
def commit_batch_view(
    batch_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_writer_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    try:
        committed = batch_service.commit_batch(client, batch_id)
    except batch_service.EntradaConflictError:
        # Re-render preview with an error overlay so the operator can
        # inspect which record collided with an existing one. If the
        # staging rows have been removed in the meantime (e.g., another
        # operator cancelled the batch), surface 404 instead of a stale
        # preview.
        staging = batch_service.get_batch(client, batch_id)
        if staging is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        return _templates.TemplateResponse(
            request=request,
            name="entradas/batch_preview.html",
            context={
                "user": user,
                "batch": staging,
                "error": (
                    "Conflicto durante el commit: alguna entrada del lote ya "
                    "existe en la base de datos. Revisa y vuelve a previsualizar."
                ),
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    if not committed:
        # Empty result means the staging rows were gone (cancelled by
        # another operator, or the link is stale). Surface 404 instead
        # of silently redirecting to /entradas with no entries created.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(
        url="/entradas",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{batch_id}/cancel", response_class=HTMLResponse)
def cancel_batch_view(
    batch_id: str,
    request: Request,
    user: Annotated[Response | dict, Depends(require_writer_user)],
    client: Annotated[InsForgeClient, Depends(get_insforge_client_dep)],
):
    if (early := return_early_if_response(user)) is not None:
        return early
    batch_service.cancel_batch(client, batch_id)
    return RedirectResponse(
        url="/entradas/batch/new",
        status_code=status.HTTP_303_SEE_OTHER,
    )
