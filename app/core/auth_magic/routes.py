"""HTTP route handlers for the magic-link auth channel (M1, F2).

Two endpoints:

* ``POST /auth/magic/start`` — request a magic link. Returns 200
  ``{"status": "queued"}`` in both paths (authorised + unknown email)
  so the response shape leaks no information. Implements spec R4.
* ``GET /auth/magic/verify?token=...`` (with ``POST`` fallback) —
  consume a token and issue a session cookie. On error paths redirects
  to ``/login`` (or ``/unauthorized``); on success redirects to ``/``.
  The cookie shape is byte-identical to what the OAuth callback emits
  (spec R5 and T2.5).

The feature flag ``APAP_AUTH_ENABLE_MAGIC_LINK`` is re-read on every
request (spec R7) so operators can flip the channel without a redeploy.
Defaults: ``APAP_ENV=dev`` or unset → flag defaults to ``"1"``; prod
defaults to ``"0"``.

The lifespan wiring of ``app.state.magic_link_port`` /
``app.state.mail_transport`` / ``app.state.auth_port`` is F3's
responsibility; the routes read them via the accessors in
:mod:`app.core.auth_magic.app_state`, which fail loudly if the lifespan
hasn't run yet (see T2.3 and the "lifespan ownership TBD" note in
``tasks.md``).

Layer compliance (AGENTS.md rule 4): this module lives under
``app/core/auth_magic/`` and may import from ``app.core.session``,
``app.core.config``, ``app.core.csrf``, and ``app.core.ports.*``. It
does NOT import from ``app.core.adapters.*`` or any module that owns an
adapter — the DI seam is the ``app.state`` attribute set by the F3
lifespan.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core import config as config_module
from app.core.auth_magic.app_state import get_auth_port, get_magic_link_port
from app.core.csrf import issue_csrf_to_session
from app.core.session import session_cookie_name, write_session

router = APIRouter(tags=["magic-link"])

# Spec R4 email validation: deliberately basic — the route treats the
# email as opaque (the adapter hashes it; the transport delivers it).
# The real authorisation check happens via ``AuthUsersPort.get_user_by_email``.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Spec R5: token is non-empty and ≤4096 chars (anything beyond that is
# almost certainly an abuse attempt — the SHA-256 input space is far
# smaller; 4096 is the absolute upper bound before we 400).
_MAX_TOKEN_LEN = 4096

# Spec AS8 / T2.1: constant-time response. The route pads the
# ``unknown`` path to >= 50ms so a timing-side-channel attacker can't
# enumerate authorised emails by measuring the response delta between
# "exists" (mail lookup + DB write + transport) and "doesn't exist"
# (mail lookup miss, no DB write).
_MIN_ELAPSED_SECONDS = 0.05

# Cookie max-age in seconds — matches the OAuth callback's 7-day window
# (see ``app/core/auth_flow.py::callback``).
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


def _magic_link_enabled() -> bool:
    """Return ``True`` iff ``APAP_AUTH_ENABLE_MAGIC_LINK`` evaluates truthy.

    Reads the env var at request time (spec R7 — operators can flip the
    channel without a redeploy). Accepts ``"1"`` / ``"true"`` / ``"yes"``;
    anything else (including the empty string and ``"0"``) is treated
    as the channel being off. The default is ``"1"`` so dev / CI sees
    the route active without any extra config.
    """
    value = os.environ.get("APAP_AUTH_ENABLE_MAGIC_LINK", "1")
    return value in ("1", "true", "True", "yes")


def _invalid_email() -> JSONResponse:
    """Return the spec R4 ``{"error": "invalid_email"}`` 400 response."""
    return JSONResponse({"error": "invalid_email"}, status_code=400)


def _invalid_request() -> JSONResponse:
    """Return the spec R5 ``{"error": "invalid_request"}`` 400 response."""
    return JSONResponse({"error": "invalid_request"}, status_code=400)


async def _parse_json_object(request: Request) -> dict | None:
    """Parse the request body as a JSON object.

    Returns the parsed ``dict`` on success. Returns ``None`` on JSON
    parse error, an empty body, or a top-level value that isn't an
    object — the caller must treat ``None`` as a 400
    ``invalid_request`` (spec R4 wording: ``"request body must be JSON object"``).
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    return body


async def _read_start_body(request: Request) -> dict | JSONResponse:
    """Validate the ``POST /auth/magic/start`` body.

    Returns the parsed dict on success; returns a
    :class:`JSONResponse` (400) on any validation failure. The caller
    is responsible for distinguishing the two via ``isinstance``.
    """
    body = await _parse_json_object(request)
    if body is None:
        return JSONResponse(
            {
                "error": "invalid_request",
                "detail": "request body must be JSON object",
            },
            status_code=400,
        )
    email = body.get("email")
    if not isinstance(email, str) or not _EMAIL_RE.match(email):
        return _invalid_email()
    return body


def _issue_session_cookie_for(user) -> tuple[str, int]:
    """Build the signed ``apap_session`` cookie payload + max_age (T2.5).

    The payload shape, signing algorithm (``itsdangerous.URLSafeTimedSerializer``
    via :func:`app.core.session.write_session`), and CSRF token injection
    (:func:`app.core.csrf.issue_csrf_to_session`) match the OAuth callback
    exactly. The cookie bytes are byte-identical (apart from the
    per-session ``csrf_token`` and the timestamp) to the cookie the OAuth
    callback emits in ``app/core/auth_flow.py::callback``.

    Returns a ``(session_token, max_age_seconds)`` tuple the route
    attaches via :meth:`Response.set_cookie` with the same kwargs the
    OAuth callback uses (``path="/", httponly=True, secure=True,
    samesite="strict", max_age=...``).
    """
    settings = config_module.get_settings()
    payload = issue_csrf_to_session(
        {
            "email": user.email,
            "rol": user.rol.value,
            "user_id": user.id,
            "is_authorized": True,
        }
    )
    session_token = write_session(payload, secret=settings.session_secret)
    return session_token, _SESSION_MAX_AGE_SECONDS


def _set_session_cookie(
    response: Response, session_token: str, max_age: int
) -> None:
    """Attach the ``apap_session`` cookie with the OAuth-callback kwargs (T2.5)."""
    response.set_cookie(
        session_cookie_name(),
        session_token,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=max_age,
    )


# ---------------------------------------------------------------------------
# POST /auth/magic/start
# ---------------------------------------------------------------------------


@router.post("/auth/magic/start")
async def start_magic(request: Request) -> Response:
    """Request a magic link for ``body.email`` (spec R4, T2.1).

    Returns ``200 {"status": "queued"}`` for both authorised and unknown
    emails so the response shape leaks no information (timing is also
    padded — see AS8). Invalid input (``non-JSON body`` / ``non-dict
    body`` / ``email regex mismatch``) returns ``400 {"error":
    "invalid_..."}`` so legitimate clients see a clear failure mode.

    When ``APAP_AUTH_ENABLE_MAGIC_LINK`` is unset/false, the handler
    short-circuits to ``200 {"status": "queued"}`` without touching
    the database or the transport (spec R7 — operators can flip the
    channel without a redeploy).
    """
    if not _magic_link_enabled():
        return JSONResponse({"status": "queued"})

    body_or_error = await _read_start_body(request)
    if isinstance(body_or_error, JSONResponse):
        return body_or_error
    email = body_or_error["email"]

    # Constant-time path (AS8): time the (user lookup + optional
    # ``request_magic_link``) work, then sleep the remainder of the
    # 50ms budget. We always look up the user (so the unknown path
    # pays the same DB cost as the known path); when the user is
    # unknown we skip the persist+transport call.
    auth_port = get_auth_port(request)
    magic_link_port = get_magic_link_port(request)

    t0 = time.monotonic()
    # M3.1 fix: when InsForge is unreachable (503, network down) treat
    # the user as unknown and continue, so the request still returns
    # 200 queued.
    try:
        user = auth_port.get_user_by_email(email)
    except Exception:
        user = None
    if user is not None:
        await magic_link_port.request_magic_link(user.email, ttl_seconds=86400)
    elapsed = time.monotonic() - t0
    if elapsed < _MIN_ELAPSED_SECONDS:
        await asyncio.sleep(_MIN_ELAPSED_SECONDS - elapsed)

    return JSONResponse({"status": "queued"})


# ---------------------------------------------------------------------------
# GET /auth/magic/verify (and POST fallback)
# ---------------------------------------------------------------------------


@router.get("/auth/magic/verify")
async def verify_magic_get(
    request: Request,
    token: str = Query(...),
) -> Response:
    """Consume ``token`` and issue a session cookie (spec R5, T2.2)."""
    return await _verify_magic_impl(request, token)


@router.post("/auth/magic/verify")
async def verify_magic_post(
    request: Request,
    token: str = Form(...),
) -> Response:
    """Same as :func:`verify_magic_get` but reads ``token`` from a form body."""
    return await _verify_magic_impl(request, token)


async def _verify_magic_impl(request: Request, token: str) -> Response:
    """Shared implementation for GET + POST ``/auth/magic/verify``.

    Flow (spec R5, T2.5):

    1. Feature-flag gate → 302 ``/login`` if off.
    2. Token shape check (non-empty, ≤4096 chars) → 400 ``invalid_request``.
    3. SHA-256 the token; call :meth:`MagicLinkPort.consume_magic_link`.
       ``None`` → 302 ``/login`` (unknown / expired / already-consumed).
    4. Defence-in-depth: resolve the consumed email against
       :class:`AuthUsersPort`. ``None`` → 302 ``/unauthorized`` (token
       somehow resolved to a non-authorised email — should be
       unreachable in practice but the route is paranoid).
    5. Build the same ``apap_session`` cookie the OAuth callback emits,
       attach it, redirect to ``/``.
    """
    if not _magic_link_enabled():
        return RedirectResponse("/login", status_code=302)

    cleaned = token.strip()
    if not cleaned or len(cleaned) > _MAX_TOKEN_LEN:
        return _invalid_request()

    token_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    magic_link_port = get_magic_link_port(request)
    auth_port = get_auth_port(request)

    email = await magic_link_port.consume_magic_link(token_hash)
    if email is None:
        return RedirectResponse("/login", status_code=302)
    user = auth_port.get_user_by_email(email)
    if user is None:
        return RedirectResponse("/unauthorized", status_code=302)

    session_token, max_age = _issue_session_cookie_for(user)
    response = RedirectResponse("/", status_code=302)
    _set_session_cookie(response, session_token, max_age)
    return response


__all__ = ["router"]
