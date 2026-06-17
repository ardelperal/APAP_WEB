"""FastAPI application entrypoint for APAP_WEB.

The application is built following the skeleton outlined in
``docs/architecture-insforge-stack.md`` and the acceptance criteria
of issue #17 (Fase 1 — esqueleto de la aplicación web). It exposes:

- ``GET /``         → landing page rendered from a Jinja2 template
- ``GET /healthz``  → JSON health probe used by Docker / Coolify (CD-02)
- ``GET /unauthorized`` → friendly access-denied page (copy is
                          provisional; the final copy arrives in Fase 2)
- ``/static/...``   → compiled CSS and other static assets
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan.

    Reserved for future startup/shutdown work (InsForge client warmup,
    cache priming, etc.). Kept explicit so tests using ``with TestClient
    (app) as client:`` exercise the full lifespan.
    """
    yield


def create_app() -> FastAPI:
    """Application factory.

    A factory (rather than a module-level instance) keeps tests
    hermetic and lets future phases spin up variants of the app.
    """
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/static",
        StaticFiles(directory=_STATIC_DIR),
        name="static",
    )

    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe.

        Returns a minimal JSON payload. CD-02 (issue #1) and Coolify
        poll this endpoint to confirm the container is ready to serve
        traffic.
        """
        return {"status": "ok", "app": settings.app_name}

    @application.get("/", response_class=HTMLResponse)
    def index(request: Request):
        """Landing page rendered from ``templates/index.html``."""
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "app_name": settings.app_name,
                "version": settings.version,
            },
        )

    @application.get("/unauthorized", response_class=HTMLResponse)
    def unauthorized(request: Request):
        """Access-denied page rendered from ``templates/unauthorized.html``.

        The current copy is provisional; the final version with
        administrative contact information arrives with Fase 2
        (authentication and the ``authorized_users`` allowlist).
        """
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={"app_name": settings.app_name},
        )

    return application


app = create_app()
