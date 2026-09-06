"""FastAPI application entrypoint for APAP_WEB.

The application is built following the skeleton outlined in
``docs/architecture/architecture-insforge-stack.md`` and the acceptance criteria
of issue #17 (Fase 1 — esqueleto) and #16 (Fase 2 — auth). It exposes:

- ``GET /``              → marketing landing page (auth required)
- ``GET /healthz``       → JSON health probe used by Docker / Coolify (CD-02, public)
- ``GET /login``         → renders the APAP login page (public)
- ``GET /auth/google``   → starts the InsForge-hosted Google OAuth flow (public)
- ``GET /auth/callback`` → exchanges the ``insforge_code`` (or legacy ``code``)
                             for an InsForge JWT and issues a session cookie
- ``GET /logout``        → clears the session cookie (any user)
- ``GET /unauthorized``  → friendly access-denied page (auth required,
                             including deactivated sessions so they see the
                             friendly copy instead of being bounced to /login)
- ``GET /admin``         → developer-only user management panel
- ``/static/...``        → compiled CSS and other static assets

Authenticated app routes (``/animales``, ``/entradas``,
``/voluntarios``, ``/admin``) are protected by the auth chain installed
in :func:`app.core.middleware.install_auth_middleware`, which checks
the signed session cookie BEFORE FastAPI runs route / form
validation. The middleware never opens a DB connection.

``PUBLIC_PATHS`` and ``_is_public_path`` are re-exported below for
backwards compatibility with tests and any out-of-tree consumers that
imported them from ``app.main``.

Spec home: ``openspec/changes/auth-insforge-hosted-proxy/specs/auth-oauth/spec.md``
for the OAuth callback contract; ``openspec/changes/ci-cd-foundation/``
for the deploy webhook contract.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core import config as config_module
from app.core.admin_handlers import register_admin_routes
from app.core.auth import ensure_schema_and_seed
from app.core.auth_dependencies import (
    get_current_user_optional,
    require_authorized_user,
    return_early_if_response,
)
from app.core.auth_dependencies import (
    get_insforge_client_dep as get_insforge_client,  # noqa: F401  - re-exported for test backwards compat
)
from app.core.auth_flow import register_auth_flow_routes
from app.core.catalogs import ensure_catalogs
from app.core.csrf import csrf_token_context_processor
from app.core.dashboard_data import DASHBOARD_PENDING_CARDS, DASHBOARD_SHORTCUTS
from app.core.di.insforge_error_handler_di import get_insforge_error_handler_port
from app.core.domain import ensure_domain_schema
from app.core.e2e_auth import register_e2e_auth_routes
from app.core.insforge import InsForgeClient
from app.core.insforge_error_handler import register_insforge_error_handler
from app.core.logging import configure_logging
from app.core.middleware import (
    DISABLED_DOC_PATHS as _DISABLED_DOC_PATHS,  # noqa: F401  - re-export for parity with PUBLIC_PATHS
)
from app.core.middleware import (
    PUBLIC_PATHS,  # noqa: F401  - re-exported for backwards compat with tests
    UADetectionMiddleware,  # noqa: F401  - re-exported for tests/test_middleware.py
    _is_public_path,  # noqa: F401  - re-exported for tests/test_public_paths.py
    base_template_context_processor,
    install_auth_middleware,
    install_rate_limit_middleware,
)
from app.core.migration.sql_runner import apply_sql_migrations
from app.core.request_context import CorrelationIdMiddleware
from app.routes_registry import register_routers

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan.

    On startup, bootstrap the InsForge schema:

    1. ``configure_logging(settings)`` — installs the JSON stdout
       handler + redaction filter so even startup errors are visible
       in Coolify / log aggregators. MUST be the first line so the
       bootstrap steps below are logged on failure. Slice 6 (REQ-4).
    2. ``ensure_schema_and_seed`` — creates ``usuarios_autorizados`` and seeds
       the bootstrap admin if ``APAP_INITIAL_ADMIN_EMAIL`` is set.
    3. ``ensure_catalogs`` — creates the 5 reference-data catalog
       tables (``catalogos_origenes``, ``catalogos_motivos``,
       ``catalogos_pruebas``, ``catalogos_periodicidad``,
       ``catalogos_tipos_contrato``) and seeds them from the Access
       legacy (issue #65 CATALOG-01). Idempotent: ``CREATE TABLE IF
       NOT EXISTS`` + ``INSERT ... ON CONFLICT DO NOTHING``.
    4. ``ensure_domain_schema`` — creates the domain tables
       (``animales``, ``voluntarios``, ``roles_voluntario``, ...) in
       dependency order. This runs after catalogs because ``contratos``
       and ``actuacion_sanitaria`` declare catalog FKs.
    5. ``apply_sql_migrations`` — applies any pending versioned SQL
       migrations from ``app/core/migration/sql/`` (schema-plane DDL,
       e.g. dropping a redundant CHECK constraint). Runs LAST so the
       earlier tables are guaranteed to exist before any migration
       references them.

    All four schema steps are idempotent (``CREATE TABLE IF NOT EXISTS``,
    ``ON CONFLICT DO NOTHING``, ``web_sql_migrations`` bookkeeping,
    ``DROP CONSTRAINT IF EXISTS``), so it is safe to run on every cold
    start. If any step raises, the lifespan propagates and the app
    does not start (fail fast): a deploy that cannot reach InsForge
    with the service key is better surfaced as a failed deploy than
    as 500s on the first request.
    """
    settings = config_module.get_settings()
    configure_logging(settings)
    # §32.P2 (issue #275): refuse to boot with missing/placeholder/short secrets.
    if not settings.debug:
        # lazy-import: only needed in production; avoids loading config at startup in dev.
        from app.core.config import _validate_secrets
        _validate_secrets(settings)
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    _.state.insforge_client = client
    try:
        ensure_schema_and_seed(client, settings)
        ensure_catalogs(client)
        ensure_domain_schema(client)
        apply_sql_migrations(client)
        yield
    finally:
        client.close()


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=302)


def create_app() -> FastAPI:
    """Application factory.

    A factory (rather than a module-level instance) keeps tests
    hermetic and lets future phases spin up variants of the app.

    The factory wires:
    1. Static files and Jinja2 templates.
    2. Middleware stack (rate-limit → auth → security-headers).
    3. Application-level route handlers (health, index, auth flow, admin).
    4. Domain routers via ``register_routers``.
    """
    settings = config_module.get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Static files
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    application.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Templates (created here so they can be shared by auth-flow and admin handlers)
    templates = Jinja2Templates(
        directory=_TEMPLATES_DIR,
        context_processors=[
            csrf_token_context_processor,
            base_template_context_processor,
        ],
    )
    # Expose templates on ``app.state`` so the FastAPI DI helper for
    # the admin slice (:func:`app.core.di.admin_di.get_admin_template_adapter`)
    # can resolve the same shared instance. The helper wraps it in
    # ``AdminTemplateAdapter`` per request.
    application.state.templates = templates

    # Middleware stack — order is load-bearing (issue #286 D8):
    # RateLimit MUST be innermost so CSRF rejections do NOT consume
    # the rate budget. install_rate_limit_middleware is called FIRST,
    # then install_auth_middleware adds CsrfMiddleware inside the chain.
    # See tests/test_middleware_order.py for the pinned order.
    # CorrelationIdMiddleware (issue #334): added FIRST so it appears LAST
    # in the middleware list (innermost), catching requests after the auth
    # chain — sufficient for request_id in log lines.
    application.add_middleware(CorrelationIdMiddleware)
    install_rate_limit_middleware(application, settings)
    install_auth_middleware(application, settings)

    # Application-level route handlers
    _register_health_handler(application, settings)
    _register_index_handler(application, templates, settings)
    _register_unauthorized_handler(application, templates, settings)
    register_auth_flow_routes(application, templates)
    # E2E test-only OAuth mock (issue #598). No-op unless
    # ``Settings.e2e_auth_enabled`` is True. Production deployments
    # leave that off and the route is not registered.
    register_e2e_auth_routes(application)
    register_admin_routes(application, templates)

    # Domain routers (issue #204)
    register_routers(application)

    return application


def _register_health_handler(app: FastAPI, settings) -> None:
    """Register the liveness probe at ``/healthz``."""

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}


def _register_index_handler(app: FastAPI, templates, settings) -> None:
    """Register the landing page at ``/``."""
    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        current_user: Annotated[Response | dict, Depends(require_authorized_user)],
    ):
        if (early := return_early_if_response(current_user)) is not None:
            return early
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "app_name": settings.app_name,
                "product_name": "APAP Alcalá",
                "version": settings.version,
                "user": current_user,
                "dashboard_cards": DASHBOARD_PENDING_CARDS,
                "dashboard_shortcuts": DASHBOARD_SHORTCUTS,
            },
        )


def _register_unauthorized_handler(app: FastAPI, templates, settings) -> None:
    """Register the access-denied page at ``/unauthorized``."""
    @app.get("/unauthorized", response_class=HTMLResponse)
    def unauthorized(
        request: Request,
        current_user: Annotated[dict | None, Depends(get_current_user_optional)],
    ):
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={"app_name": settings.app_name, "product_name": "APAP Alcalá"},
        )


app = create_app()

# §32.P4 (issues #277, #278): register a global handler that converts
# any unhandled InsForgeError into a non-leaking 502. Lives in its own
# module so the §21 700-line budget on ``app/main.py`` stays intact.
# Slice #420: the handler now receives the translation port via DI
# (the adapter is the only file that imports InsForgeError).
register_insforge_error_handler(app, get_insforge_error_handler_port())
