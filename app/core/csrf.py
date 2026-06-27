"""CSRF defense-in-depth helpers and middleware (PR-5B, Slice 5).

This module closes the HIGH finding (F-1) from
``docs/audits/auth-dependencies-audit-2026-Q2.md``: every state-changing
request (``POST`` / ``PUT`` / ``PATCH`` / ``DELETE``) must present a
CSRF token that matches the one stored in the user's signed session
payload.

The defense is layered:

1. ``SameSite=Strict`` on ``apap_session`` and ``apap_pkce`` cookies
   (REQ-AH-5) — closes the CSRF gap for browsers that honor Strict.
2. Per-session CSRF token issued at ``/auth/callback`` (REQ-AH-6) —
   stored under ``payload["csrf_token"]`` in the signed cookie.
3. ``CsrfMiddleware`` validates the token on every non-safe request
   (REQ-AH-8) using a timing-safe comparison (``hmac.compare_digest``).
4. The token transport is dual: ``X-CSRFToken`` header for AJAX-style
   callers AND ``csrf_token`` form field for traditional HTML forms
   (REQ-AH-7). The middleware tries the header first (cheaper, no body
   read) and falls back to the form field on ``application/x-www-form-urlencoded``
   or ``multipart/form-data`` requests.
5. A feature flag (``Settings.csrf_enabled``) and a logging placeholder
   (T-5B.27) keep the middleware reversible without a redeploy:
   ``APAP_CSRF_ENABLED=false`` short-circuits the check, and Slice 6
   will swap the ``logging.warning`` placeholder for ``log_safe()``
   with the same event name (``"csrf.rejected"``) so observability
   stays neutral.

The logging placeholder is intentional: Slice 6 swaps
``logging.getLogger(__name__).warning("csrf.rejected", extra=...)``
for ``log_safe("csrf.rejected", ...)``. The event name MUST stay
``csrf.rejected`` so downstream dashboards and redaction tests don't
need to change after the swap.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.session import read_session, session_cookie_name

SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

CSRF_HEADER = "X-CSRFToken"
"""Header name used by AJAX callers to transport the CSRF token."""

CSRF_FORM_FIELD = "csrf_token"
"""Form field name used by traditional HTML forms to transport the CSRF token."""

_FORM_CONTENT_TYPES: tuple[str, ...] = (
    "application/x-www-form-urlencoded",
    "multipart/form-data",
)


def generate_csrf_token() -> str:
    """Return a fresh CSRF token (>= 256 bits of entropy).

    Uses ``secrets.token_urlsafe(32)`` (32 random bytes, URL-safe
    base64). Output is always >= 32 chars (typical: 43) and uses only
    ``[A-Za-z0-9_-]``, so it can be embedded in HTML attribute values
    and HTTP headers without escaping.
    """
    return secrets.token_urlsafe(32)


def issue_csrf_to_session(payload: dict) -> dict:
    """Return a copy of ``payload`` with a fresh ``csrf_token`` field.

    Called by ``/auth/callback`` after a successful OAuth exchange.
    The token is signed into the session cookie and stays valid until
    the session is invalidated (logout, SESSION_SECRET rotation, or
    expiry) — there is no per-request token rotation because the
    project does not use HTMX yet (verified pre-slice, see audit
    doc §"Pre-slice form audit").
    """
    return {**payload, "csrf_token": generate_csrf_token()}


def _extract_provided_token(request: Request) -> str | None:
    """Read the CSRF token from the request (header first, form fallback).

    Returns the first non-empty value found, or ``None``. Form fallback
    is a hint only — the actual ``await request.form()`` call lives in
    the middleware because form parsing is async (Starlette requirement).
    """
    provided = request.headers.get(CSRF_HEADER)
    if provided:
        return provided
    # Starlette canonicalizes ``X-CSRFToken`` but be lenient on the case
    # in case the caller used ``x-csrftoken`` or similar.
    for header_name, header_value in request.headers.items():
        if header_name.lower() == CSRF_HEADER.lower() and header_value:
            return header_value
    return None


def _extract_form_token(request: Request) -> str | None:
    """Read the CSRF token from the parsed form body (helper for tests).

    Real callers MUST use the middleware's async form parsing. This
    synchronous helper exists so unit tests can exercise the
    "form field path" branch without spinning up the middleware.
    """
    # No synchronous request body parser exists in Starlette; tests that
    # need this path go through the middleware.
    return None


class CSRFValidationError(Exception):
    """Raised when CSRF validation fails.

    NOT an HTTPException (Rule 7): 403 responses are produced by the
    middleware itself, not by raising into FastAPI's error pipeline.
    """


class CsrfMiddleware(BaseHTTPMiddleware):
    """Validate CSRF tokens on POST/PUT/PATCH/DELETE for protected paths.

    Reads ``Settings.csrf_enabled`` at request time (not import time) so
    a ``get_settings.cache_clear()`` + env change can disable the
    middleware without redeploy.

    The middleware does NOT short-circuit GET/HEAD/OPTIONS — those are
    safe by RFC 7231. ``/auth/callback`` is GET, so it bypasses CSRF
    (verified in PR-1A's SB-3 resolution: ``PUBLIC_PATHS`` includes
    ``/auth/callback`` so the auth layer doesn't block it either).
    """

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._logger = logging.getLogger(__name__)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in SAFE_METHODS:
            # GET/HEAD/OPTIONS still benefit from ``request.state.csrf_token``
            # being populated so templates that render forms with
            # ``{{ csrf_token }}`` work even on safe methods.
            self._populate_csrf_state(request)
            return await call_next(request)

        settings = get_settings()
        if not settings.csrf_enabled:
            # Placeholder for Slice 6 swap to ``log_safe("csrf.disabled")``.
            # Event name MUST stay stable so dashboards don't break.
            self._logger.warning("csrf.disabled")
            self._populate_csrf_state(request)
            return await call_next(request)

        # Read session cookie + decode payload.
        token = request.cookies.get(session_cookie_name())
        payload = (
            read_session(token, secret=settings.session_secret)
            if token
            else None
        )
        expected = payload.get("csrf_token") if payload else None
        # Expose the token on ``request.state`` so templates can render
        # ``<input type="hidden" name="csrf_token" value="{{ csrf_token }}>``
        # in their context. Routes inject ``csrf_token=request.state.csrf_token``
        # into each TemplateResponse call.
        request.state.csrf_token = expected

        # Token transport: header first (cheap), then form field.
        provided = _extract_provided_token(request)
        if not provided:
            content_type = request.headers.get("content-type", "")
            if any(content_type.startswith(ct) for ct in _FORM_CONTENT_TYPES):
                form = await request.form()
                value = form.get(CSRF_FORM_FIELD)
                if isinstance(value, str):
                    provided = value

        if not expected or not provided or not hmac.compare_digest(
            str(expected), str(provided)
        ):
            # Slice 6 will swap this for ``log_safe("csrf.rejected",
            # path=..., reason=...)``. Event name MUST stay stable.
            self._logger.warning(
                "csrf.rejected",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "reason": (
                        "missing_session" if not expected
                        else "missing_token" if not provided
                        else "token_mismatch"
                    ),
                },
            )
            return JSONResponse(
                {"error": "CSRF token missing or invalid"},
                status_code=403,
            )

        return await call_next(request)

    @staticmethod
    def _populate_csrf_state(request: Request) -> None:
        """Populate ``request.state.csrf_token`` from the session cookie.

        Safe to call on every request. Returns ``""`` when there is no
        session or the payload is missing the field (defensive default
        so templates that render ``{{ csrf_token }}`` don't blow up on
        unauthenticated GETs).
        """
        try:
            token = request.cookies.get(session_cookie_name())
        except Exception:
            request.state.csrf_token = ""
            return
        if not token:
            request.state.csrf_token = ""
            return
        try:
            payload = read_session(
                token, secret=get_settings().session_secret
            )
        except Exception:
            request.state.csrf_token = ""
            return
        request.state.csrf_token = (
            payload.get("csrf_token", "") if payload else ""
        )
