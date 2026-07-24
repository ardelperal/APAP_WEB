"""Project-wide HTTP middleware and Jinja context glue.

Single import surface for everything auth-and-middleware in
``app/main.py``. Holds:

- ``UADetectionMiddleware`` — set ``request.state.is_mobile`` per
  request so routes / templates can opt into device-specific
  rendering (UA-based template selection, architectural decision
  per engram obs #15705). Slice A of the UA-based templates work.

- ``_select_base_template`` / ``base_template_context_processor`` —
  turn ``request.state.is_mobile`` into a ``base_template`` Jinja
  variable. Templates ``{% extends base_template %}`` resolve to
  ``base_mobile.html`` for mobile users and ``base.html`` for
  desktop. Slice B of the UA-based templates work.

- ``install_auth_middleware`` — single entry point that wires the
  full auth-related middleware chain (``CsrfMiddleware`` →
  ``protect_user_facing_routes`` → ``UADetectionMiddleware``) on a
  ``FastAPI`` instance. Extracted from ``app/main.py`` as part of
  issue #204; the pre-refactor ordering and conditional behaviour
  are preserved exactly.

- Auth-path helpers (``PUBLIC_PATHS``, ``DISABLED_DOC_PATHS``,
  ``_is_public_path``) moved from ``app/main.py`` so the file can
  shrink to a thin factory. ``app/main.py`` re-exports the
  constants and helper for backwards-compatible imports
  (test_public_paths.py).

Future middleware additions (rate limiting, CSP hardening, etc.)
land here as separate files; this module stays the single import
surface for ``app/main.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.core.csrf import CsrfMiddleware
from app.core.session import read_session_payload
from app.core.ua import is_mobile

# Template filenames selected by the UA-based template selector.
# Kept module-level constants so the processor stays cheap to call
# per-render and so tests can assert against the literal strings
# without constructing a full Request.
BASE_TEMPLATE_DESKTOP = "base.html"
BASE_TEMPLATE_MOBILE = "base_mobile.html"


# --- auth-path helpers (moved from app/main.py in #204) -------------------

# Public paths that the auth layer must never block.
# The landing page (/) and the access-denied page (/unauthorized) are
# intentionally protected so the marketing surface can only be reached
# after OAuth — the modules list links to authenticated app routes and
# must not leak the org's structure to anonymous probers. Only the
# technical exceptions below bypass the middleware.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/login",
        "/auth/google",
        "/auth/callback",
        "/logout",
    }
)
DISABLED_DOC_PATHS: frozenset[str] = frozenset({"/docs", "/redoc", "/openapi.json"})


def _is_public_path(path: str) -> bool:
    """Return whether ``path`` is intentionally reachable without a session."""
    return path in PUBLIC_PATHS or path == "/static" or path.startswith("/static/")


# --- UA middleware --------------------------------------------------------


def _select_base_template(request: Request) -> str:
    """Devuelve el nombre del base template segun el device del request.

    Slice B del UA-based template selection (obs engram #15705).
    Lee ``request.state.is_mobile`` (poblado por
    ``UADetectionMiddleware`` en slice A) y devuelve
    ``BASE_TEMPLATE_MOBILE`` o ``BASE_TEMPLATE_DESKTOP``.

    Default-deny: si ``is_mobile`` no esta presente en
    ``request.state`` (p.ej. tests que construyen un ``Request``
    sin pasar por la cadena ASGI completa), devuelve el template
    desktop. Misma postura que
    ``csrf_token_context_processor`` con
    ``getattr(request.state, "csrf_token", "") or ""``.

    Args:
        request: ``Request`` activo en el render. Solo se lee
            ``request.state.is_mobile``.

    Returns:
        Nombre del template (``"base.html"`` o
        ``"base_mobile.html"``) que los templates ``pages/*.html``
        deben extender con ``{% extends base_template %}``.
    """
    is_mobile_request = bool(getattr(request.state, "is_mobile", False))
    return BASE_TEMPLATE_MOBILE if is_mobile_request else BASE_TEMPLATE_DESKTOP


def base_template_context_processor(request: Request) -> dict[str, str]:
    """Jinja context processor: expone ``base_template`` segun device.

    Usado por ``app/main.py`` (y, en futuras migraciones de
    modulos, por las instancias ``Jinja2Templates`` de cada
    router) en su lista ``context_processors=[...]``. Asi, cada
    ``TemplateResponse`` recibe automaticamente
    ``base_template`` en el contexto y los templates pueden
    escribir ``{% extends base_template %}`` sin tener que
    hardcodear el nombre.

    Implementacion: delega en ``_select_base_template`` para que
    el contrato (``is_mobile`` → ``"base_mobile.html"`` /
    ``"base.html"``) viva en un unico sitio. Esta funcion solo
    adapta la salida a la forma dict que espera
    ``Jinja2Templates``.
    """
    return {"base_template": _select_base_template(request)}


class UADetectionMiddleware(BaseHTTPMiddleware):
    """Detect mobile User-Agent and flag ``request.state.is_mobile``.

    Default: ``is_mobile=False`` (desktop) — explicit opt-in per
    request, no false positives. A missing ``User-Agent`` header is
    treated as "not a browser" and therefore not mobile.

    The middleware is purely additive: it never short-circuits,
    never raises, and never logs. All detection logic lives in
    :func:`app.core.ua.is_mobile`, which keeps the regex testable
    in isolation and reusable from any future context (e.g. a
    background job that preprocesses a User-Agent without an
    actual request).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Populate ``request.state.is_mobile`` and forward the request."""
        ua = request.headers.get("user-agent")
        request.state.is_mobile = is_mobile(ua)
        return await call_next(request)


# --- auth chain installer (issue #204) ------------------------------------


def _redirect(path: str) -> RedirectResponse:
    """Internal 302 helper used by the auth middleware below."""
    return RedirectResponse(url=path, status_code=302)


def install_auth_middleware(app: FastAPI, settings) -> None:
    """Wire the full auth-related middleware chain on ``app``.

    Issue #204: extracted from ``app/main.py`` so the factory can
    shrink to a thin shell. The chain (and ordering) is identical
    to the pre-refactor ``app/main.py:create_app``:

    1. ``CsrfMiddleware`` (conditional on ``settings.csrf_enabled``)
       — registered first via ``add_middleware``. PR-5B2 (REQ-AH-8)
       feature-flag gated for emergency rollback.
    2. ``protect_user_facing_routes`` — registered via Starlette's
       ``@app.middleware("http")`` decorator, which wraps the
       function in ``BaseHTTPMiddleware`` and stores it at the
       front of ``app.user_middleware``. Pre-refactor this lived
       inline at ``app/main.py:267-293``; the body is moved here
       verbatim, including the default-deny
       ``payload.get("is_authorized", False)`` contract.
    3. ``UADetectionMiddleware`` — registered LAST via
       ``add_middleware``; because Starlette inserts at position 0,
       it becomes the OUTERMOST at request time. Pre-refactor
       comment at ``app/main.py:296-302`` pinned this ordering.

    Order on a request (outermost -> innermost):
    ``UADetectionMiddleware`` -> ``protect_user_facing_routes``
    -> ``CsrfMiddleware`` -> app routes.

    Args:
        app: ``FastAPI`` instance to configure. Mutated in place.
        settings: ``app.core.config.Settings`` (typed as object to
            avoid the import cycle flagged by Detector 11; the
            installer reads only ``csrf_enabled`` and
            ``session_secret`` from it).
    """
    # CSRF defense-in-depth (PR-5B2, REQ-AH-8). Registered AFTER the
    # static-files mount and BEFORE the auth middleware below so the
    # token check can read the session cookie (which Starlette decodes
    # via the cookie machinery above). Feature-flag gated for
    # emergency rollback (``APAP_CSRF_ENABLED=false``); see
    # ``csrf.py`` docstring for the Slice 6 logging-swap contract.
    if settings.csrf_enabled:
        app.add_middleware(CsrfMiddleware)

    @app.middleware("http")
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

        payload = read_session_payload(
            request, secret=settings.session_secret
        )
        if not payload:
            return _redirect("/login")
        if path == "/unauthorized":
            return await call_next(request)
        if not payload.get("is_authorized", False):
            return _redirect("/unauthorized")
        return await call_next(request)

    # UA-based device detection (slice A of UA-based templates, obs #15705).
    # Placed AFTER the auth middleware so that, in Starlette's stack
    # (``add_middleware`` inserts at position 0 → last call is outermost),
    # ``UADetectionMiddleware`` runs FIRST on every request — before the
    # auth redirect can short-circuit, before CsrfMiddleware handles the
    # token, and before any route handler reads ``request.state.is_mobile``.
    # The middleware is purely additive (never short-circuits, never logs);
    # the per-request cost is one regex match in ``app.core.ua.is_mobile``.
    app.add_middleware(UADetectionMiddleware)
