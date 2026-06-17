"""FastAPI application entrypoint for APAP_WEB.

The application is built following the skeleton outlined in
``docs/architecture-insforge-stack.md`` and the acceptance criteria
of issue #17 (Fase 1 — esqueleto) and #16 (Fase 2 — auth). It exposes:

- ``GET /``              → landing page (public; shows user info if logged in)
- ``GET /healthz``       → JSON health probe used by Docker / Coolify (CD-02)
- ``GET /login``         → starts the Google OAuth flow (public)
- ``GET /auth/callback`` → exchanges the OAuth code for an InsForge JWT
                            and issues a session cookie
- ``GET /logout``        → clears the session cookie (any user)
- ``GET /unauthorized``  → friendly access-denied page (public)
- ``GET /admin``         → developer-only user management panel
- ``/static/...``        → compiled CSS and other static assets
"""

from __future__ import annotations

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
    get_user_by_email,
    list_authorized_users,
)
from app.core.insforge import InsForgeClient
from app.core.pkce import generate_pkce_pair
from app.core.session import (
    clear_session_cookie_params,
    read_session,
    session_cookie_name,
    write_session,
)

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Public paths that the auth layer must never block.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/healthz",
        "/login",
        "/auth/callback",
        "/unauthorized",
        "/logout",
    }
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Application lifespan.

    Reserved for future startup/shutdown work (InsForge client warmup,
    cache priming, etc.). Kept explicit so tests using the ASGITransport
    ``with`` block exercise the full lifespan.
    """
    yield


def get_insforge_client() -> InsForgeClient:
    """FastAPI dependency: produce an InsForge REST client per request.

    Tests can override this with ``app.dependency_overrides[...]``.
    """
    settings = config_module.get_settings()
    return InsForgeClient(settings.insforge_url, settings.insforge_service_key)


def get_current_user_optional(request: Request) -> dict | None:
    """FastAPI dependency: return the current session payload, or None."""
    settings = config_module.get_settings()
    token = request.cookies.get(session_cookie_name())
    if not token:
        return None
    return read_session(token, secret=settings.session_secret)


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
    def index(
        request: Request,
        current_user: dict | None = Depends(get_current_user_optional),
    ):
        """Landing page rendered from ``templates/index.html``."""
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
    def unauthorized(request: Request):
        """Access-denied page rendered from ``templates/unauthorized.html``.

        The current copy is provisional; the final version with
        administrative contact information arrives with the closing
        of the auth slice.
        """
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
        ``authorized_users``; authorized users get a signed session
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

        session_token = write_session(
            {
                "email": user["email"],
                "role": user["role"],
                "user_id": user["id"],
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
        current_user: dict | None = Depends(get_current_user_optional),
        client: InsForgeClient = Depends(get_insforge_client),
    ):
        """Developer-only user management panel.

        Authorization is enforced again (not just trusted from the
        cookie) so a stale developer record cannot keep the panel
        accessible after the user is deactivated.
        """
        if not current_user:
            return _redirect("/login")
        if current_user.get("role") != "developer":
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
        current_user: dict | None = Depends(get_current_user_optional),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Add a new authorized user. Developer only."""
        if not current_user or current_user.get("role") != "developer":
            return _redirect("/unauthorized")
        form = await request.form()
        email = str(form.get("email", "")).strip()
        role = str(form.get("role", "")).strip()
        if not email or not role:
            return _redirect("/admin")
        try:
            add_authorized_user(
                client,
                email=email,
                role=role,
                added_by=current_user["user_id"],
            )
        except ValueError:
            return _redirect("/admin")
        return _redirect("/admin")

    @application.post("/admin/users/{user_id}/deactivate")
    def admin_deactivate_user(
        user_id: str,
        current_user: dict | None = Depends(get_current_user_optional),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Deactivate an authorized user. Developer only."""
        if not current_user or current_user.get("role") != "developer":
            return _redirect("/unauthorized")
        deactivate_authorized_user(client, user_id)
        return _redirect("/admin")

    return application


app = create_app()

