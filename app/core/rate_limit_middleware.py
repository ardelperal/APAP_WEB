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
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.e2e_auth import AUDIT_TARGET_EMAIL_MAX_LEN
from app.core.logging import log_safe
from app.core.rate_limit import (
    RateLimitBackend,
    RetryInfo,
    _extract_identity,
)

if TYPE_CHECKING:
    from app.core.config import Settings

# Safe HTTP methods — not subject to rate limits (but OAuth callback IS
# subject even though it is a GET — it is not a read, it is an OAuth action).
SAFE_METHODS = frozenset({"HEAD", "OPTIONS"})

# HTTP methods that count as writes for rate-limit purposes
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Route-specific ceiling for the E2E mock login (issue #904 AC2):
# 5 attempts/minute/IP. A module constant (not a Settings field) keeps
# the guard autonomous from config and it is only a backstop — the
# shared secret remains the primary gate.
E2E_LOGIN_RATE_LIMIT_PER_MIN = 5

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
    - E2E login: ``GET /e2e/login`` — IP-only, 5/min (issue #904), ONLY
      when the route is registered (``e2e_auth_enabled`` True; with the
      flag off the endpoint answers a bare 404 like any unknown path).
    - Write: POST/PUT/PATCH/DELETE — both user-id and IP, default 60/min
      and 30/min; the tighter bucket wins.
    - Read: HEAD/OPTIONS — no limit (but GET /auth/callback and
      GET /e2e/login ARE limited).

    Headers on every protected response (REQ-1, D5):
    - ``X-RateLimit-Limit``: bucket ceiling.
    - ``X-RateLimit-Remaining``: requests left in window.
    - ``X-RateLimit-Reset``: epoch seconds when the window clears.

    Rejection: HTTP 429 with ``Retry-After`` + JSON ``{"error": "Rate limit exceeded"}``.
    Log on rejection: ``log_safe("ratelimit.rejected", path, reason, scope, user_id)``
    with NO IP kwarg (REQ-5, D6) — plus, for the ``e2e_login`` scope only,
    one additional IP-bearing forensic ``e2e.login`` event (issue #904
    fix round 1, JD-B-003) because brute-force bursts against the gate
    must leave an attributable trail.

    APAP_MODE=test bypass: all checks short-circuit, no state mutated (REQ-4, D7).
    """

    def __init__(self, app: Callable[..., Awaitable[None]], backend: RateLimitBackend) -> None:
        super().__init__(app)
        self._backend = backend

    async def _handle_e2e_login(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """IP-limited bucket for GET /e2e/login (issue #904 AC2).

        5 attempts/minute/IP; the 6th gets the shared 429 shape. Success
        responses carry the rate-limit headers like the OAuth bucket.
        """
        # Read settings at request time so test patches take effect.
        # lazy-import: avoids circular import with app.core.session.
        from app.core.config import get_settings

        identity = _extract_identity(request, get_settings())
        allowed, info = self._backend.hit(
            scope="e2e_login",
            identity=identity.ip or "unknown",
            limit=E2E_LOGIN_RATE_LIMIT_PER_MIN,
            now=_monotonic_now(),
            window_seconds=60,
        )
        if not allowed:
            log_safe(
                "ratelimit.rejected",
                path=request.url.path,
                reason="ip",
                scope="e2e_login",
                user_id=identity.user_id,
            )
            # Forensic event for this scope ONLY (issue #904 fix round 1,
            # JD-B-003): ``ratelimit.rejected`` carries no IP by design
            # (REQ-5/D6) and is shared across scopes, so a brute-force
            # burst against the gate would lose the source IP and the
            # attempted email. The e2e login gate additionally emits an
            # IP-bearing ``e2e.login`` entry with a capped raw email;
            # every other scope keeps the rejection log unchanged.
            raw_email = request.query_params.get("email")
            log_safe(
                "e2e.login",
                outcome="rate_limited",
                target_email=(raw_email or "").strip()[:AUDIT_TARGET_EMAIL_MAX_LEN],
                client_ip=identity.ip or "unknown",
            )
            return _build_429_response(info)
        response = await call_next(request)
        return _add_rate_limit_headers(response, info)

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
        is_oauth_callback = path == "/auth/callback" and method == "GET"
        is_write = method in WRITE_METHODS

        if is_oauth_callback:
            identity = _extract_identity(request, settings)
            scope = "oauth"
            identity_key = identity.ip or "unknown"
            limit = settings.rate_limit_oauth_per_min
            allowed, info = self._backend.hit(
                scope=scope,
                identity=identity_key,
                limit=limit,
                now=_monotonic_now(),
                window_seconds=60,
            )
            reason = None if allowed else "ip"
            response = await call_next(request)
            if allowed:
                response = _add_rate_limit_headers(response, info)
            else:
                log_safe(
                    "ratelimit.rejected",
                    path=path,
                    reason=reason,
                    scope=scope,
                    user_id=identity.user_id,
                )
                return _build_429_response(info)
            return response

        if is_write:
            identity = _extract_identity(request, settings)
            # User bucket
            if identity.user_id:
                user_allowed, user_info = self._backend.hit(
                    scope="write_user",
                    identity=identity.user_id,
                    limit=settings.rate_limit_write_per_min_user,
                    now=_monotonic_now(),
                    window_seconds=60,
                )
            else:
                user_allowed = True
                user_info = RetryInfo(
                    allowed=True, limit=0, remaining=0, reset_at=0.0, retry_after=None
                )
            # IP bucket
            ip_allowed, ip_info = self._backend.hit(
                scope="write_ip",
                identity=identity.ip or "unknown",
                limit=settings.rate_limit_write_per_min_ip,
                now=_monotonic_now(),
                window_seconds=60,
            )
            # Tighter bucket wins
            if not ip_allowed:
                allowed, info, reason = False, ip_info, "ip"
            elif not user_allowed:
                allowed, info, reason = False, user_info, "user"
            else:
                # Both allowed — record against more-exhausted bucket for header accuracy
                allowed, info = True, (user_info if user_info.remaining <= ip_info.remaining else ip_info)
                reason = None
            response = await call_next(request)
            if allowed:
                response = _add_rate_limit_headers(response, info)
            else:
                log_safe(
                    "ratelimit.rejected",
                    path=path,
                    reason=reason,
                    scope="write",
                    user_id=identity.user_id,
                )
                return _build_429_response(info)
            return response

        # HEAD/OPTIONS pass through unrated; plain GETs too, except the
        # E2E mock login when its route is registered (see _handle_unprotected).
        return await self._handle_unprotected(request, call_next, settings)

    async def _handle_unprotected(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        settings: Settings,
    ) -> Response:
        """HEAD/OPTIONS and plain GETs — no rate limit, except e2e login.

        The E2E mock login (issue #904 AC2) is IP-limited ONLY when the
        route is actually registered (``Settings.e2e_auth_enabled`` True).
        With the flag off the route does not exist, so a probe must get
        the same bare 404 as any unknown path — no rate-limit headers and
        no bucket consumption — so the disabled endpoint cannot be
        fingerprinted through the limiter (issue #904 fix round 1,
        JD-B-001/JD-A-003). Everything else passes through unrated.
        """
        if settings.e2e_auth_enabled and _is_e2e_login_request(
            request.method, request.url.path
        ):
            return await self._handle_e2e_login(request, call_next)
        return await call_next(request)


def _is_e2e_login_request(method: str, path: str) -> bool:
    """Whether this request targets the E2E mock login bucket (issue #904)."""
    return path == "/e2e/login" and method == "GET"


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
