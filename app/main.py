"""FastAPI application entrypoint for APAP_WEB.

The application is built following the skeleton outlined in
``docs/architecture-insforge-stack.md`` and the acceptance criteria
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

Issue #204 extracted the auth-middleware setup (issue #204) and the
domain-router registration (``register_routers``) out of this file,
leaving it as a thin factory: ``create_app`` now boots the FastAPI
instance, mounts ``/static``, calls ``install_auth_middleware``, hands
the lifespan over to schema bootstrap, declares the auth flow routes
(``/login``, ``/auth/google``, ``/auth/callback``, ``/logout``) plus
the admin and marketing handlers, and finally delegates every domain
router to :func:`app.routes_registry.register_routers`. The
``PUBLIC_PATHS`` constant and the ``_is_public_path`` helper are
re-exported below for backwards compatibility with tests and any
out-of-tree consumers that imported them from ``app.main``.

Spec home: ``openspec/changes/auth-insforge-hosted-proxy/specs/auth-oauth/spec.md``
for the OAuth callback contract; ``openspec/changes/ci-cd-foundation/``
for the deploy webhook contract.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
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
    require_developer_user_redirect,
    return_early_if_response,
)
from app.core.auth_dependencies import (
    get_insforge_client_dep as get_insforge_client,
)
from app.core.catalogs import ensure_catalogs
from app.core.config import _validate_secrets
from app.core.csrf import csrf_token_context_processor, issue_csrf_to_session
from app.core.domain import ensure_domain_schema
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.logging import configure_logging, log_safe
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
from app.core.pkce import generate_pkce_pair
from app.core.session import (
    clear_session_cookie_params,
    read_session,
    session_cookie_name,
    write_session,
)
from app.routes_registry import register_routers

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

_DASHBOARD_PENDING_CARDS = [
    {
        "label": "Animales incoherentes",
        "description": "Revisa fichas con datos que necesitan contraste antes de continuar la gestión.",
    },
    {
        "label": "Pendientes de entrada",
        "description": "Animales que aún necesitan completar su entrada en protectora.",
    },
    {
        "label": "Pendientes de nueva situación",
        "description": "Fichas que esperan registrar el siguiente cambio de estado operativo.",
    },
    {
        "label": "Pendientes de chip",
        "description": "Animales cuya identificación debe comprobarse o completarse.",
    },
    {
        "label": "Cambio de titular pendiente",
        "description": "Casos que requieren seguimiento hasta cerrar el cambio de titularidad.",
    },
    {
        "label": "Fallecidos sin RIAC",
        "description": "Animales fallecidos con comunicación RIAC pendiente de registrar.",
    },
    {
        "label": "Impresos por entregar",
        "description": "Documentación preparada que todavía debe llegar a su destinatario.",
    },
    {
        "label": "Impresos entregados no recibidos",
        "description": "Documentos entregados que aún no constan como recibidos o adjuntados.",
    },
    {
        "label": "Seguimientos activos",
        "description": "Adopciones y casos abiertos que necesitan atención próxima.",
    },
    {
        "label": "Seguimientos totales",
        "description": "Vista de control para medir la carga completa de seguimiento.",
    },
]

_DASHBOARD_SHORTCUTS = [
    {"label": "Buscar animal", "href": "/animales", "description": "Consulta o actualiza una ficha."},
    {"label": "Nueva entrada", "href": "/entradas", "description": "Registra una llegada a protectora."},
    {"label": "Voluntarios", "href": "/voluntarios", "description": "Gestiona personas colaboradoras."},
]


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
    # REQ-4 (Slice 6): configure_logging is the FIRST line so any error
    # in the steps below is captured by the JSON stdout handler with
    # PII redaction applied.
    configure_logging(settings)
    # §32.P2 (issue #275): refuse to boot with missing/placeholder/short secrets.
    # Called AFTER configure_logging so log_safe output is captured.
    # Called BEFORE InsForgeClient(...) so no network call happens with bad config.
    # StartupConfigError propagates — the try/finally below does NOT catch it.
    if not settings.debug:
        _validate_secrets(settings)
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    # Keep one InsForgeClient (and its underlying httpx connection pool) alive
    # for the complete application lifetime. The request dependency reads
    # this exact instance from app.state instead of creating one per request.
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

    Issue #204: this factory is now thin — the auth middleware chain
    lives in :func:`app.core.middleware.install_auth_middleware` and
    the 11 ``app.include_router(...)`` calls live in
    :func:`app.routes_registry.register_routers`. The auth-flow
    handlers (``/login``, ``/auth/google``, ``/auth/callback``,
    ``/logout``, ``/admin``, ``/admin/users``) stay here because they
    are not "domain module" routes but application-level glue (they
    share ``get_insforge_client``, the templates instance, and the
    ``_redirect`` helper above).
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

    # Rate limiting on OAuth callback and write routes (issue #286).
    # Installed BEFORE install_auth_middleware so that CsrfMiddleware —
    # the LAST middleware added inside install_auth_middleware via
    # ``app.add_middleware`` — becomes the OUTERMOST in Starlette's
    # stack (Starlette's ``add_middleware`` does ``insert(0, ...)``,
    # so the most-recently-added middleware is outermost). Per D8,
    # CSRF rejections must NOT consume a legitimate user's rate
    # budget; running CSRF before rate-limit achieves that.
    install_rate_limit_middleware(application, settings)

    # Auth-related middleware chain (issue #204). Reads ``settings`` so
    # ``APAP_CSRF_ENABLED`` (Slice 5 feature flag) gates CSRF
    # registration, matching the pre-refactor conditional block at
    # ``app/main.py:256-257``. See ``app/core/middleware.py`` for the
    # chain ordering. Installed AFTER rate-limit so CsrfMiddleware
    # (added inside this function) is outermost — see the comment
    # above the rate-limit install.
    install_auth_middleware(application, settings)

    templates = Jinja2Templates(
        directory=_TEMPLATES_DIR,
        context_processors=[
            csrf_token_context_processor,
            base_template_context_processor,
        ],
    )

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
        """Landing page rendered from ``templates/index.html``.

        Protected: anonymous visitors are bounced to /login by the
        auth middleware before this handler runs (so even malformed
        POSTs cannot 422-leak the handler signature). The
        ``require_authorized_user`` dep is kept as a defence-in-depth
        check so the handler's protected status is explicit at the
        call site.
        """
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
                "dashboard_cards": _DASHBOARD_PENDING_CARDS,
                "dashboard_shortcuts": _DASHBOARD_SHORTCUTS,
            },
        )

    @application.get("/unauthorized", response_class=HTMLResponse)
    def unauthorized(
        request: Request,
        current_user: dict | None = Depends(get_current_user_optional),
    ):
        """Access-denied page rendered from ``templates/unauthorized.html``.

        Public so anonymous visitors can read the friendly denial copy
        after being bounced from a protected route. The template does not
        depend on ``current_user``; the optional dependency is kept so the
        handler signature stays stable for future personalised copy.
        """
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={"app_name": settings.app_name, "product_name": "APAP Alcalá"},
        )

    # --- Auth flow (Fase 2) --------------------------------------------

    @application.get("/login")
    def login(
        request: Request,
    ) -> Response:
        """Render APAP's login page.

        This route is intentionally passive. Starting OAuth directly from
        ``/login`` creates a redirect loop when ``/auth/callback`` cannot
        complete (for example, missing/expired PKCE cookie): callback -> login
        -> provider -> callback forever. The user must click the Gmail button,
        which posts no data and simply navigates to ``/auth/google``.
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
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"app_name": settings.app_name},
        )

    @application.get("/auth/google")
    def start_google_login(
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
            # OAuth returns to /auth/callback via a top-level cross-site GET
            # from Google/InsForge. SameSite=Strict is not sent on that
            # navigation, so the callback cannot read the verifier and starts
            # a /callback -> /login loop. Lax keeps the verifier out of
            # cross-site subrequests/forms while allowing the OAuth callback.
            samesite="lax",
            max_age=600,
        )
        return response

    @application.get("/auth/callback")
    def callback(
        request: Request,
        insforge_code: str | None = None,
        code: str | None = None,  # legacy direct-callback (pre-InsForge-proxy)
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Exchange the OAuth code for an InsForge JWT and issue a session.

        InsForge's hosted OAuth proxy fronts Google and other providers
        with a two-step flow: APAP starts the flow at ``/login`` (which
        hits ``GET /api/auth/oauth/google`` and gets back a Google OAuth
        URL); after consent, Google → InsForge → APAP with
        ``?insforge_code=<temporary>``; APAP then exchanges that code
        here via ``POST /api/auth/oauth/exchange``. The legacy
        ``?code=<google-code>`` direct-callback parameter is also
        accepted so existing test suites and any direct callbacks keep
        working.

        The ``code_verifier`` is recovered from the short-lived PKCE
        cookie minted at ``/login``. The email returned by InsForge is
        checked against ``usuarios_autorizados``; authorized users get
        a signed session cookie, everyone else is redirected to
        ``/unauthorized``.
        """
        settings = config_module.get_settings()

        pkce_token = request.cookies.get("apap_pkce")
        if not pkce_token:
            return _redirect("/login")
        pkce = read_session(pkce_token, secret=settings.session_secret)
        if not pkce or "code_verifier" not in pkce:
            return _redirect("/login")

        try:
            if insforge_code:
                exchange = client.exchange_insforge_oauth_code(
                    insforge_code=insforge_code,
                    code_verifier=pkce["code_verifier"],
                )
            elif code:
                exchange = client.exchange_google_oauth_code(
                    code=code,
                    code_verifier=pkce["code_verifier"],
                    redirect_uri=settings.google_redirect_uri,
                )
            else:
                return _redirect("/login")
        except InsForgeError:
            return _redirect("/login")

        user = get_user_by_email(client, exchange.user.email)
        if not user:
            response = _redirect("/unauthorized")
            response.delete_cookie("apap_pkce")
            return response

        # The signed cookie carries identity + advisory role (stable
        # for 7 days). ``is_authorized`` is NOT the source of truth
        # anymore — ``require_authorized_user`` (#143) re-validates
        # against ``usuarios_autorizados`` on every request via a
        # TTL cache (``Settings.auth_cache_ttl_seconds``, default
        # 300s), so an admin deactivation via
        # ``/admin/users/{id}/deactivate`` takes effect within the TTL
        # instead of waiting for the cookie to expire. The P0 VOL-01
        # fix this comment replaced is preserved as the first gate
        # (``is_authorized`` defaults to False — default-deny),
        # not as the final answer.
        #
        # PR-5B (REQ-AH-6) adds ``csrf_token`` via ``issue_csrf_to_session``
        # so the CSRF middleware (REQ-AH-8) can validate POST/PUT/PATCH/DELETE
        # without relying solely on SameSite cookies.
        session_token = write_session(
            issue_csrf_to_session(
                {
                    "email": user["email"],
                    "rol": user["rol"],
                    "user_id": user["id"],
                    "is_authorized": bool(user.get("activo", False)),
                }
            ),
            secret=settings.session_secret,
        )
        # Slice 6 sample call site (T-6.7): emit a structured
        # ``auth.login`` event. The ``email`` kwarg is REDACTED by
        # ``log_safe`` per the closed 12-field list — operators see
        # the event name and ``user_id`` (non-PII), not the email.
        # This proves the redaction filter is wired end-to-end on a
        # real authentication flow, not just in unit tests.
        log_safe("auth.login", email=user["email"], user_id=user["id"])
        response = _redirect("/")
        response.set_cookie(
            session_cookie_name(),
            session_token,
            # path="/": MUST match the /logout clearing cookie's path
            # (also "/") so the browser can match the Set-Cookie and
            # actually delete the session. Without this, the cookie
            # defaults to the request path (/auth/callback) and the
            # clearing with path="/" is IGNORED by the browser —
            # the user reported Salir does not log them out.
            path="/",
            httponly=True,
            secure=True,
            samesite="strict",
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
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
    ):
        """Developer-only user management panel.

        ``require_developer_user_redirect`` (issue #146) ya redirige a
        ``/login`` si no hay sesion, a ``/unauthorized`` si la sesion
        expiro o el rol es insuficiente (cualquier rol distinto de
        ``developer``), y emite ``log_safe("auth.denied", ...)`` en cada
        denegacion para audit trail. Antes de #146 este handler repetia
        inline ``current_user.get("rol") != "developer"`` — duplicacion
        eliminada al consolidar la comprobacion del rol en la dep.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
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
    def admin_add_user(
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
        email: str = Form(""),
        rol: str = Form(""),
    ) -> Response:
        """Add a new authorized user. Developer only.

        Sync ``def`` (not ``async def``) so FastAPI runs the handler
        in the threadpool and the sync InsForgeClient doesn't block
        the event loop. Other admin handlers use the same style.
        Form fields are declared as ``Form(...)`` parameters instead
        of pulling them out of ``await request.form()`` so the
        contract is obvious from the signature.

        Issue #146 — la dep inyectada aplica el check de developer (rol
        insuficiente → redirect ``/unauthorized`` + ``log_safe``).
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        # Narrowing: the early return above already handled the
        # Response arm, so current_user can only be the session dict.
        assert isinstance(current_user, dict)
        email = email.strip()
        rol = rol.strip()
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
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Deactivate an authorized user. Developer only.

        Issue #146 — la dep inyectada aplica el check de developer (rol
        insuficiente → redirect ``/unauthorized`` + ``log_safe``).
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        deactivate_authorized_user(client, user_id)
        return _redirect("/admin")

    # Domain router registration (issue #204). The single entry point
    # ``register_routers`` owns the include_router ordering — see
    # ``app/routes_registry.py`` for the inline rationale on each
    # router's insertion position.
    register_routers(application)

    return application


app = create_app()
