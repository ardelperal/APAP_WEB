"""Sub-router for FOSTER-03 foster assignment gate.

3 endpoints, all under ``/casas-acogida`` prefix:

- ``GET /casas-acogida/{casa_id}/asignar`` — render the evaluation form.
- ``POST /casas-acogida/{casa_id}/asignar`` — execute the gate.
- ``GET /casas-acogida/{casa_id}/overrides`` — list capacity overrides for the casa.

Same patterns as ``app/modules/foster/routes.py`` (FOSTER-01) and
``app/modules/acogidas/routes.py`` (FOSTER-02):

- Routes own NO SQL — every data access goes through ``assignment_service``.
- Auth via ``require_authorized_user`` + session payload for ``user_id``.
- CSRF token is auto-injected via ``csrf_token_context_processor``.
- All handlers call ``return_early_if_response(user)`` first (defense
  in depth — the auth middleware already bounces anonymous visitors
  to ``/login``).

The sub-router shares the ``/casas-acogida`` prefix with the FOSTER-01
``foster_router`` so the path namespace is contiguous. FastAPI's
routers are matched by registered order; ``assignment_router`` is
mounted AFTER ``foster_router`` in ``app/main.py`` so its paths
(``/{casa_id}/asignar``, ``/{casa_id}/overrides``) take precedence
over the dynamic ``/{casa_id}`` of foster_router for those exact
paths. The remaining foster routes (list/new/create/detail/edit/
update/delete) keep working unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.core.auth_dependencies import (
    get_insforge_client_dep,
    require_authorized_user,
    return_early_if_response,
)
from app.core.config import get_settings
from app.core.csrf import csrf_token_context_processor
from app.core.insforge import InsForgeClient
from app.core.session import read_session_payload
from app.modules.foster import assignment as assignment_service
from app.modules.foster import service as foster_service

router = APIRouter(prefix="/casas-acogida", tags=["foster"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
# PR-5B2 (REQ-AH-7): inject csrf_token into every template context.
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[csrf_token_context_processor],
)


# --- helpers --------------------------------------------------------------


def _operator_user_id(request: Request) -> str:
    """Return the operator's ``user_id`` from the session payload.

    Returns the empty string when the session is missing the field;
    the handler treats that as a programming error (the session is
    minted at ``/auth/callback`` with a UUID — a missing ``user_id``
    means the cookie was tampered with or the user is on a stale
    version of the auth flow).
    """
    settings = get_settings()
    payload = read_session_payload(request, secret=settings.session_secret)
    if not payload:
        return ""
    return str(payload.get("user_id") or "")


def _render_asignar_form(
    request: Request,
    user: Any,
    casa: foster_service.CasaAcogida,
    form_data: dict[str, Any],
    warning: str | None,
    error: str | None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    return _templates.TemplateResponse(
        request=request,
        name="casas_acogida/asignar.html",
        context={
            "user": user,
            "casa": casa,
            "form_data": form_data,
            "warning": warning,
            "error": error,
        },
        status_code=status_code,
    )


# --- GET /casas-acogida/{casa_id}/asignar ---------------------------------


@router.get("/{casa_id}/asignar", response_class=HTMLResponse)
def asignar_form(
    casa_id: str,
    request: Request,
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the foster assignment evaluation form.

    Loads the casa via the foster service (404 if missing). The form
    starts with empty ``animal_id`` and ``motivo``; the user types the
    animal UUID and (conditionally) the motivo if a warning fires on
    submission.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _render_asignar_form(
        request,
        user,
        casa,
        {"animal_id": "", "motivo": ""},
        warning=None,
        error=None,
    )


# --- POST /casas-acogida/{casa_id}/asignar --------------------------------


@router.post("/{casa_id}/asignar", response_class=HTMLResponse)
def asignar_submit(
    casa_id: str,
    request: Request,
    animal_id: str = Form(...),
    motivo: str = Form(""),
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Execute the gate and route the operator based on the decision.

    Outcome matrix (D-GC-04 / D-GC-05):

    - ``block``: re-render the form with status 422 and the gate's
      ``reason`` as the error message. The operator cannot proceed.
    - ``admit``: redirect 303 to ``/acogidas/new?animal_id=X&casa_acogida_id=Y``
      so the operator can complete the estancia create (FOSTER-02 flow).
    - ``admit_with_warning`` + non-empty motivo: record the override
      via ``record_override`` (insert + ``log_safe``), then 303 to
      ``/acogidas/new?animal_id=X&casa_acogida_id=Y``.
    - ``admit_with_warning`` + empty motivo: re-render the form with
      status 422 and the warning visible; the operator must provide a
      motivo to confirm.
    - ``ValueError`` from the service (animal missing, casa missing,
      casa inactive): translate to 422 with the service's message.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    form_data = {"animal_id": animal_id, "motivo": motivo}

    try:
        decision = assignment_service.evaluate_assignment(
            client, animal_id, casa_id
        )
    except ValueError as exc:
        return _render_asignar_form(
            request,
            user,
            casa,
            form_data,
            warning=None,
            error=str(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    if decision.decision == "block":
        return _render_asignar_form(
            request,
            user,
            casa,
            form_data,
            warning=None,
            error=decision.reason,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    if decision.decision == "admit":
        return RedirectResponse(
            url=f"/acogidas/new?animal_id={animal_id}&casa_acogida_id={casa_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # decision.decision == "admit_with_warning"
    motivo_clean = (motivo or "").strip()
    if not motivo_clean:
        return _render_asignar_form(
            request,
            user,
            casa,
            form_data,
            warning=decision.warnings[0] if decision.warnings else None,
            error="el motivo es obligatorio para continuar por encima de la capacidad",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    # Motivo non-empty: record override, then redirect.
    operador = _operator_user_id(request)
    if not operador:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sesion sin user_id",
        )
    assignment_service.record_override(
        client,
        casa_id=casa_id,
        animal_id=animal_id,
        operador_user_id=operador,
        motivo=motivo_clean,
    )
    return RedirectResponse(
        url=f"/acogidas/new?animal_id={animal_id}&casa_acogida_id={casa_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --- GET /casas-acogida/{casa_id}/overrides --------------------------------


@router.get("/{casa_id}/overrides", response_class=HTMLResponse)
def overrides_list(
    casa_id: str,
    request: Request,
    user: Any = Depends(require_authorized_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Render the historical list of capacity overrides for one casa.

    Sorted ``created_at DESC`` (most recent first) — see
    ``assignment_service.list_overrides_for_casa``. Empty list renders
    a friendly "sin overrides registrados" message; no error.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    casa = foster_service.get_casa_acogida_by_id(client, casa_id)
    if casa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    overrides = assignment_service.list_overrides_for_casa(client, casa_id)
    return _templates.TemplateResponse(
        request=request,
        name="casas_acogida/overrides.html",
        context={
            "user": user,
            "casa": casa,
            "overrides": overrides,
        },
    )
