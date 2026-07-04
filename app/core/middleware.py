"""Project-wide HTTP middleware and Jinja context glue.

Currently:

- ``UADetectionMiddleware`` — set ``request.state.is_mobile`` per
  request so routes / templates can opt into device-specific
  rendering (UA-based template selection, architectural decision
  per engram obs #15705). Slice A of the UA-based templates work.

- ``_select_base_template`` / ``base_template_context_processor`` —
  turn ``request.state.is_mobile`` into a ``base_template`` Jinja
  variable. Templates ``{% extends base_template %}`` resolve to
  ``base_mobile.html`` for mobile users and ``base.html`` for
  desktop. Slice B of the UA-based templates work.

Future middleware additions (rate limiting, CSP hardening, etc.)
land here as separate files; this module is the single import
surface for ``app/main.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.ua import is_mobile

# Template filenames selected by the UA-based template selector.
# Kept module-level constants so the processor stays cheap to call
# per-render and so tests can assert against the literal strings
# without constructing a full Request.
BASE_TEMPLATE_DESKTOP = "base.html"
BASE_TEMPLATE_MOBILE = "base_mobile.html"


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
