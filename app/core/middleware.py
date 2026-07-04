"""Project-wide HTTP middleware.

Currently:

- ``UADetectionMiddleware`` — set ``request.state.is_mobile`` per
  request so routes / templates can opt into device-specific
  rendering (UA-based template selection, architectural decision
  per engram obs #15705). Slice A of the UA-based templates work.

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
