"""Developer-only devtools routes (issue #821).

Registered by ``app.main`` ONLY when ``Settings.devtools_enabled`` is
True (see the ``e2e_auth`` conditional-registration pattern). When the
flag is off the router is never included and any probe to
``/devtools/...`` receives FastAPI's default 404 — there is no 503 or
permission branch to confuse with a real surface.

The routes stay behind the default-deny auth middleware: nothing here
is added to ``PUBLIC_PATHS``, so an anonymous request is redirected to
``/login`` before routing. ``require_authorized_user`` is applied per
route as defense-in-depth (same convention as every domain module).

Current surface (issue #821): the stepper component preview page, a
developer playground for the reusable form stepper — no production
form is converted in this slice.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.auth_dependencies import (
    require_authorized_user,
    return_early_if_response,
)
from app.core.csrf import csrf_token_context_processor
from app.core.middleware import (
    base_template_context_processor,
    current_path_context_processor,
)

router = APIRouter(prefix="/devtools", tags=["devtools"])

_TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_templates = Jinja2Templates(
    directory=_TEMPLATES_DIR,
    context_processors=[
        csrf_token_context_processor,
        base_template_context_processor,
        current_path_context_processor,
    ],
)


@router.get("/stepper-preview", response_class=HTMLResponse)
def stepper_preview(
    request: Request,
    current_user: Annotated[Response | dict, Depends(require_authorized_user)],
) -> Response:
    """Render the developer-only stepper component preview page."""
    if (early := return_early_if_response(current_user)) is not None:
        return early
    return _templates.TemplateResponse(
        request=request,
        name="devtools/stepper_preview.html",
        context={"user": current_user},
    )


@router.post("/stepper-preview", response_class=HTMLResponse)
def stepper_preview_submit(
    current_user: Annotated[Response | dict, Depends(require_authorized_user)],
) -> Response:
    """No-op POST target so the preview form is submittable end-to-end.

    Renders a minimal confirmation page (marker
    ``data-stepper-submitted``) that the E2E suite asserts on. No data
    is persisted; this endpoint exists only so the stepper's submit
    flow can be exercised in a browser.
    """
    if (early := return_early_if_response(current_user)) is not None:
        return early
    return HTMLResponse(
        "<!doctype html><html lang=\"es\"><head><title>Stepper preview"
        "</title></head><body><h1>Formulario recibido</h1>"
        "<p data-stepper-submitted>El formulario del stepper se envió "
        "correctamente (vista previa, sin persistencia).</p>"
        '<a href="/devtools/stepper-preview">Volver a la vista previa</a>'
        "</body></html>"
    )
