"""Rate-limit middleware (issue #286, REQ-1, REQ-2, D1, D5-D7).

Provides:
- ``RateLimitMiddleware`` — Starlette ``BaseHTTPMiddleware`` applying
  three independent buckets: OAuth callback (IP-only, 10/min),
  write routes (both user and IP, 60/min and 30/min), and read routes
  (no limit).
- All protected responses receive ``X-RateLimit-{Limit,Remaining,Reset}``.
- Rejections return HTTP 429 with ``Retry-After`` and log via
  ``log_safe("ratelimit.rejected", path, reason, scope, user_id)``.
- ``APAP_MODE=test`` short-circuits before any bucket access.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.logging import log_safe
from app.core.rate_limit import (
    RateLimitBackend,
    RetryInfo,
    _extract_identity,
)

# Safe HTTP methods — not subject to rate limits (but OAuth callback IS
# subject even though it is a GET — it is not a read, it is an OAuth action).
SAFE_METHODS = frozenset({"HEAD", "OPTIONS"})

# HTTP methods that count as writes for rate-limit purposes
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Module-level backend instance — set by install_rate_limit_middleware.
# Tests can call _reset_rate_limit_backend() to clear bucket state between runs.
_rate_limit_backend: RateLimitBackend | None = None


def _reset_rate_limit_backend() -> None:
    """Clear all rate-limit bucket state (for test isolation)."""
    if _rate_limit_backend is not None:
        _rate_limit_backend.reset()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit OAuth callback and write routes (REQ-1, REQ-2).

    Installed AFTER ``CsrfMiddleware`` via
    ``install_rate_limit_middleware`` so CSRF rejections do not consume
    a legitimate user's rate budget (D8).

    Settings are read at request time via ``get_settings()`` (not stored
    at init), so that tests can mutate ``APAP_MODE`` via
    ``get_settings.cache_clear()`` + monkeypatch.

    Three buckets (REQ-2):
    - OAuth: ``GET /auth/callback`` — IP-only, default 10/min.
    - Write: POST/PUT/PATCH/DELETE — both user-id and IP, default 60/min
      and 30/min; the tighter bucket wins.
    - Read: HEAD/OPTIONS — no limit (but GET /auth/callback IS limited).

    Headers on every protected response (REQ-1, D5):
    - ``X-RateLimit-Limit``: bucket ceiling.
    - ``X-RateLimit-Remaining``: requests left in window.
    - ``X-RateLimit-Reset``: epoch seconds when the window clears.

    Rejection: HTTP 429 with ``Retry-After`` + JSON ``{"error": "Rate limit exceeded"}``.
    Log on rejection: ``log_safe("ratelimit.rejected", path, reason, scope, user_id)``
    with NO IP kwarg (REQ-5, D6).

    APAP_MODE=test bypass: all checks short-circuit, no state mutated (REQ-4, D7).
    """

    def __init__(self, app: Callable[..., Awaitable[None]], backend: RateLimitBackend) -> None:
        super().__init__(app)
        self._backend = backend

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Read settings at request time so test patches take effect.
        # lazy-import: avoids circular import with app.core.session.
        from app.core.config import get_settings

        settings = get_settings()

        # Test-mode bypass — no state mutated, no 429 issued
        if settings.mode == "test":
            return await call_next(request)

        method = request.method
        path = request.url.path

        # OAuth callback — always rate-limited even though it is a GET
        if path == "/auth/callback" and method == "GET":
            return await self._dispatch_oauth_callback(request, call_next, settings, path)
        if method in WRITE_METHODS:
            return await self._dispatch_write(request, call_next, settings, path)
        # HEAD/OPTIONS or GET (non-OAuth callback) — passthrough, no rate limit.
        return await call_next(request)

    async def _dispatch_oauth_callback(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        settings: Settings,
        path: str,
    ) -> Response:
        """OAuth callback branch (IP-only, default 10/min) extracted from :meth:`dispatch`."""
        identity = _extract_identity(request, settings)
        identity_key = identity.ip or "unknown"
        limit = settings.rate_limit_oauth_per_min
        allowed, info = self._backend.hit(
            scope="oauth",
            identity=identity_key,
            limit=limit,
            now=_monotonic_now(),
            window_seconds=60,
        )
        response = await call_next(request)
        if allowed:
            return _add_rate_limit_headers(response, info)
        log_safe(
            "ratelimit.rejected",
            path=path,
            reason="ip",
            scope="oauth",
            user_id=identity.user_id,
        )
        return _build_429_response(info)

    async def _dispatch_write(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        settings: Settings,
        path: str,
    ) -> Response:
        """Write route branch (both user-id and IP buckets, tighter wins) extracted from :meth:`dispatch`."""
        identity = _extract_identity(request, settings)
        user_allowed, user_info = self._user_bucket_result(identity, settings)
        ip_allowed, ip_info = self._ip_bucket_result(identity, settings)
        allowed, info, reason = _pick_stricter(
            ip_allowed, ip_info, user_allowed, user_info
        )
        response = await call_next(request)
        if allowed:
            return _add_rate_limit_headers(response, info)
        log_safe(
            "ratelimit.rejected",
            path=path,
            reason=reason,
            scope="write",
            user_id=identity.user_id,
        )
        return _build_429_response(info)

    def _user_bucket_result(
        self,
        identity: object,
        settings: Settings,
    ) -> tuple[bool, RetryInfo]:
        """Check the user bucket; no-op (allow) when the request has no user identity."""
        if identity.user_id:
            return self._backend.hit(
                scope="write_user",
                identity=identity.user_id,
                limit=settings.rate_limit_write_per_min_user,
                now=_monotonic_now(),
                window_seconds=60,
            )
        return True, RetryInfo(
            allowed=True, limit=0, remaining=0, reset_at=0.0, retry_after=None
        )

    def _ip_bucket_result(
        self,
        identity: object,
        settings: Settings,
    ) -> tuple[bool, RetryInfo]:
        """Check the IP bucket."""
        return self._backend.hit(
            scope="write_ip",
            identity=identity.ip or "unknown",
            limit=settings.rate_limit_write_per_min_ip,
            now=_monotonic_now(),
            window_seconds=60,
        )


def _pick_stricter(
    ip_allowed: bool,
    ip_info: RetryInfo,
    user_allowed: bool,
    user_info: RetryInfo,
) -> tuple[bool, RetryInfo, str | None]:
    """Choose the tighter of two rate-limit buckets.

    Returns ``(allowed, info, reason)``: when both buckets allow the request,
    ``info`` is the more-exhausted bucket (lower remaining) so the
    ``X-RateLimit-Remaining`` header is conservative. When one bucket
    rejects, that bucket's info is returned with the matching reason.
    """
    if not ip_allowed:
        return False, ip_info, "ip"
    if not user_allowed:
        return False, user_info, "user"
    return True, (user_info if user_info.remaining <= ip_info.remaining else ip_info), None


def _add_rate_limit_headers(response: Response, info: RetryInfo) -> Response:
    """Inject rate-limit headers into a response (D5)."""
    response.headers["X-RateLimit-Limit"] = str(info.limit)
    response.headers["X-RateLimit-Remaining"] = str(info.remaining)
    response.headers["X-RateLimit-Reset"] = str(int(info.reset_at))
    return response


def _build_429_response(info: RetryInfo) -> JSONResponse:
    """Build a 429 response with Retry-After and X-RateLimit-* headers (REQ-1)."""
    headers = {
        "Retry-After": str(info.retry_after),
        "X-RateLimit-Limit": str(info.limit),
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int(info.reset_at)),
    }
    return JSONResponse(
        {"error": "Rate limit exceeded"},
        status_code=429,
        headers=headers,
    )


def _monotonic_now() -> float:
    """Wrapper for time.monotonic — allows controlled faking in tests."""
    return time.monotonic()
