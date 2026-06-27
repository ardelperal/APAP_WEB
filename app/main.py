"""FastAPI application entrypoint for APAP_WEB.

The application is built following the skeleton outlined in
``docs/architecture-insforge-stack.md`` and the acceptance criteria
of issue #17 (Fase 1 — esqueleto) and #16 (Fase 2 — auth). It exposes:

- ``GET /``              → landing page (requires login/authorization)
- ``GET /healthz``       → JSON health probe used by Docker / Coolify (CD-02)
- ``GET /login``         → starts the Google OAuth flow (public)
- ``GET /auth/callback`` → exchanges the OAuth code for an InsForge JWT
                            and issues a session cookie
- ``GET /logout``        → clears the session cookie (any user)
- ``GET /unauthorized``  → friendly access-denied page (requires a session)
- ``GET /admin``         → developer-only user management panel
- ``/static/...``        → compiled CSS and other static assets
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core import config as config_module
from app.core.auth import (
    VALID_ROLES,
    add_authorized_user,
    deactivate_authorized_user,
    ensure_schema_and_seed,
    get_user_by_email,
    list_authorized_users,
)
from app.core.auth_dependencies import (
    get_current_user_optional,
    require_authorized_user,
    return_early_if_response,
)
from app.core.auth_dependencies import (
    get_insforge_client_dep as get_insforge_client,
)
from app.core.domain import ensure_domain_schema
from app.core.insforge import InsForgeClient
from app.core.migration.sql_runner import apply_sql_migrations
from app.core.pkce import generate_pkce_pair
from app.core.session import (
    clear_session_cookie_params,
    read_session,
    session_cookie_name,
    write_session,
)
from app.modules.animals.routes import router as animals_router
from app.modules.entradas.routes import router as entradas_router
from app.modules.voluntarios.routes import router as voluntarios_router

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Public paths that the auth layer must never block.
PUBLIC_PATHS = frozenset(
    {
        "/healthz",
        "/login",
        "/auth/callback",
        "/logout",
    }
)
DISABLED_DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


def _is_public_path(path: str) -> bool:
    """Return whether ``path`` is intentionally reachable without a session."""
    return path in PUBLIC_PATHS or path == "/static" or path.startswith("/static/")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan.

    On startup, bootstrap the InsForge schema:

    1. ``ensure_schema_and_seed`` — creates ``usuarios_autorizados`` and seeds
       the bootstrap admin if ``APAP_INITIAL_ADMIN_EMAIL`` is set.
    2. ``ensure_domain_schema`` — creates the domain tables
       (``animales``, ``voluntarios``, ``roles_voluntario``) in dependency
       order.
    3. ``apply_sql_migrations`` — applies any pending versioned SQL
       migrations from ``app/core/migration/sql/`` (schema-plane DDL,
       e.g. dropping a redundant CHECK constraint). Runs LAST so the
       ``usuarios_autorizados`` table is guaranteed to exist before any
       migration references it.

    All three steps are idempotent (``CREATE TABLE IF NOT EXISTS``,
    ``web_sql_migrations`` bookkeeping, ``DROP CONSTRAINT IF EXISTS``),
    so it is safe to run on every cold start. If any step raises, the
    lifespan propagates and the app does not start (fail fast): a
    deploy that cannot reach InsForge with the service key is better
    surfaced as a failed deploy than as 500s on the first request.
    """
    settings = config_module.get_settings()
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    try:
        ensure_schema_and_seed(client, settings)
        ensure_domain_schema(client)
        apply_sql_migrations(client)
    finally:
        client.close()
    yield


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=302)


def create_app() -> FastAPI:
    """Application factory.

    A factory (rather than a module-level instance) keeps tests
    hermetic and lets future phases spin up variants of the app.
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

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/static",
        StaticFiles(directory=_STATIC_DIR),
        name="static",
    )

    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @application.middleware("http")
    async def protect_user_facing_routes(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Authenticate user-facing routes before route/body validation.

        Handler-level ``Depends(require_authorized_user)`` runs after FastAPI
        resolves request parameters, so malformed anonymous form posts can hit
        ``Form(...)`` validation and return 422 before the handler can redirect.
        This middleware uses only the signed session cookie and never opens a DB
        connection, which keeps auth-before-validation cheap and deterministic.
        """
        path = request.url.path
        if _is_public_path(path) or path in DISABLED_DOC_PATHS:
            return await call_next(request)

        token = request.cookies.get(session_cookie_name())
        payload = (
            read_session(token, secret=settings.session_secret)
            if token
            else None
        )
        if not payload:
            return _redirect("/login")
        if path == "/unauthorized":
            return await call_next(request)
        if not payload.get("is_authorized", False):
            return _redirect("/unauthorized")
        return await call_next(request)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe.

        Returns a minimal JSON payload. CD-02 (issue #1) and Coolify
        poll this endpoint to confirm the container is ready to serve
        traffic.
        """
        return {"status": "ok", "app": settings.app_name}

    @application.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        current_user: Response | dict = Depends(require_authorized_user),
    ):
        """Landing page rendered from ``templates/index.html``."""
        if (early := return_early_if_response(current_user)) is not None:
            return early
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "app_name": settings.app_name,
                "version": settings.version,
                "user": current_user,
            },
        )

    @application.get("/unauthorized", response_class=HTMLResponse)
    def unauthorized(
        request: Request,
        current_user: dict | None = Depends(get_current_user_optional),
    ):
        """Access-denied page rendered from ``templates/unauthorized.html``.

        Anonymous users should not see app-facing pages other than the
        login flow. Users with a session but without authorization can
        see the friendly access-denied copy.
        """
        if current_user is None:
            return _redirect("/login")
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={"app_name": settings.app_name},
        )

    # --- Auth flow (Fase 2) --------------------------------------------

    @application.get("/login")
    def login(
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Start the Google OAuth flow via InsForge.

        Generates a PKCE pair, stores the verifier in a short-lived
        ``apap_pkce`` cookie, asks InsForge for the Google auth URL
        and redirects the user there.
        """
        settings = config_module.get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            return JSONResponse(
                {
                    "error": (
                        "Google OAuth no está configurado: define "
                        "APAP_GOOGLE_CLIENT_ID y APAP_GOOGLE_CLIENT_SECRET."
                    )
                },
                status_code=503,
            )

        code_verifier, code_challenge = generate_pkce_pair()
        auth_url = client.start_google_oauth(
            settings.google_redirect_uri, code_challenge
        )

        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            "apap_pkce",
            write_session(
                {"code_verifier": code_verifier}, secret=settings.session_secret
            ),
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=600,
        )
        return response

    @application.get("/auth/callback")
    def callback(
        code: str,
        request: Request,
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Exchange the OAuth code for an InsForge JWT and issue a session.

        The ``code_verifier`` is recovered from the short-lived PKCE
        cookie. The email returned by InsForge is checked against
        ``usuarios_autorizados``; authorized users get a signed session
        cookie, everyone else is redirected to ``/unauthorized``.
        """
        settings = config_module.get_settings()

        pkce_token = request.cookies.get("apap_pkce")
        if not pkce_token:
            return _redirect("/login")
        pkce = read_session(pkce_token, secret=settings.session_secret)
        if not pkce or "code_verifier" not in pkce:
            return _redirect("/login")

        exchange = client.exchange_google_oauth_code(
            code=code,
            code_verifier=pkce["code_verifier"],
            redirect_uri=settings.google_redirect_uri,
        )
        user = get_user_by_email(client, exchange.user.email)
        if not user:
            response = _redirect("/unauthorized")
            response.delete_cookie("apap_pkce")
            return response

        # ``is_authorized`` se escribe aqui (no se lee) y queda
        # congelado en la cookie hasta que expire. El fix del P0 de
        # la code review VOL-01 vive en este write: sin el flag,
        # ``require_authorized_user`` lo lee con default True y la
        # desactivacion de un usuario via /admin/users/{id}/deactivate
        # no tomaba efecto hasta que la cookie expiraba (7 dias).
        session_token = write_session(
            {
                "email": user["email"],
                "rol": user["rol"],
                "user_id": user["id"],
                "is_authorized": bool(user.get("activo", False)),
            },
            secret=settings.session_secret,
        )
        response = _redirect("/")
        response.set_cookie(
            session_cookie_name(),
            session_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
        response.delete_cookie("apap_pkce")
        return response

    @application.get("/logout")
    def logout() -> Response:
        """Clear the session cookie and redirect home."""
        response = _redirect("/")
        response.set_cookie(**clear_session_cookie_params())
        return response

    # --- Admin panel (developer only) ---------------------------------

    @application.get("/admin", response_class=HTMLResponse)
    def admin(
        request: Request,
        current_user: Response | dict = Depends(require_authorized_user),
        client: InsForgeClient = Depends(get_insforge_client),
    ):
        """Developer-only user management panel.

        ``require_authorized_user`` ya redirige a ``/login`` si no hay
        sesion y a ``/unauthorized`` si ``is_authorized=False``, asi que
        aca solo queda chequear el rol. Eso cierra el gap P2-inherited
        detectado en la primera revision del PR #90: un developer
        desactivado por otro developer no podia seguir entrando con su
        cookie vieja.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        if current_user.get("rol") != "developer":
            return _redirect("/unauthorized")
        users = list_authorized_users(client)
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "app_name": settings.app_name,
                "current_user": current_user,
                "users": users,
                "roles": sorted(VALID_ROLES),
            },
        )

    @application.post("/admin/users")
    async def admin_add_user(
        request: Request,
        current_user: Response | dict = Depends(require_authorized_user),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Add a new authorized user. Developer only."""
        if (early := return_early_if_response(current_user)) is not None:
            return early
        if current_user.get("rol") != "developer":
            return _redirect("/unauthorized")
        form = await request.form()
        email = str(form.get("email", "")).strip()
        rol = str(form.get("rol", "")).strip()
        if not email or not rol:
            return _redirect("/admin")
        try:
            add_authorized_user(
                client,
                email=email,
                role=rol,
                added_by=current_user["user_id"],
            )
        except ValueError:
            return _redirect("/admin")
        return _redirect("/admin")

    @application.post("/admin/users/{user_id}/deactivate")
    def admin_deactivate_user(
        user_id: str,
        current_user: Response | dict = Depends(require_authorized_user),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Deactivate an authorized user. Developer only."""
        if (early := return_early_if_response(current_user)) is not None:
            return early
        if current_user.get("rol") != "developer":
            return _redirect("/unauthorized")
        deactivate_authorized_user(client, user_id)
        return _redirect("/admin")

    application.include_router(animals_router)
    application.include_router(entradas_router)
    application.include_router(voluntarios_router)

    return application


app = create_app()

