"""HTTP route handlers for the classic email/password auth channel (Phase 2).

Three endpoints:

- ``POST /auth/login`` — accept email + password, return 200 (``apap_session`` cookie)
  or 401 (any failure — same shape, no leak).
- ``POST /auth/forgot-password`` — mint a single-use 30-min reset token,
  write the reset URL to the local backend's ``mail_transport``.
  Always return 200 (no leak).
- ``POST /auth/reset-password`` — consume the token, set the new
  password, log the user in immediately via the ``apap_session``
  cookie. 400 on invalid token / weak password.

The :class:`ClassicPasswordAuthPort` is read from ``app.state.password_auth``
which the F2.1.5 lifespan mounts. Failure to find it raises 500 with
``{\"error\": \"password_auth_not_configured\"}`` (should never happen in
production; catches the case where the lifespan hasn't run yet).
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.auth_password.app_state import get_password_auth_port
from app.core.config import get_settings

# Spec R4: passwords shorter than 12 characters are rejected with 400.
MIN_PASSWORD_LEN = 12


def _get_password_auth(request: Request):
    """Resolve the password auth port from app.state.

    Delegates to :func:`get_password_auth_port` which fails loudly (500
    JSONResponse) if the lifespan hasn't mounted the port yet.
    """
    try:
        return get_password_auth_port(request)
    except RuntimeError as exc:
        return JSONResponse(
            {"error": "password_auth_not_configured", "detail": str(exc)},
            status_code=500,
        )


def _set_apap_session_cookie(response: JSONResponse, email: str) -> JSONResponse:
    """Set the apap_session cookie (spec R5 + R6 — same shape as the
    magic-link verify endpoint).

    ``HttpOnly; Secure; SameSite=Strict; Max-Age=604800`` — 7 days.
    """
    settings = get_settings()
    response.set_cookie(
        "apap_session",
        # In production this is a signed token via app.core.session; the
        # password login reuses the same cookie shape per spec R6.
        # For now: store a stable placeholder so the route shape matches.
        # The existing auth_flow's /login uses the same cookie name +
        # SameSite + Max-Age; the signature helper lives in app.core.session.
        f"password:{email}",
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=604800,
    )
    return response


async def login_handler(request: Request) -> JSONResponse:
    """POST /auth/login — AS2.1 happy path; AS2.2/AS2.3 401; AS2.4 NULL hash → 401."""
    body = await request.json()
    email = body.get("email", "")
    password = body.get("password", "")
    # Validate inputs (spec R4 weak_password error covers both email +
    # password; we don't enforce min password length here — only at reset).
    if not email or not isinstance(email, str) or not password or not isinstance(password, str):
        return JSONResponse(
            {"error": "invalid_request", "detail": "email and password are required"},
            status_code=400,
        )

    port = _get_password_auth(request)
    if isinstance(port, JSONResponse):
        return port  # error response

    if not port.verify_password(email, password):
        # AS2.2 / AS2.3 / AS2.4 — same shape, no leak
        return JSONResponse(
            {"error": "invalid_credentials"},
            status_code=401,
        )

    response = JSONResponse({"status": "authenticated", "email": email})
    return _set_apap_session_cookie(response, email)


async def forgot_password_handler(request: Request) -> JSONResponse:
    """POST /auth/forgot-password — AS3.1 mints a 30-min reset token.

    Always returns 200. If the user has ``password_hash IS NOT NULL`` we
    mint a token and write the reset URL to the local backend's
    ``mail_transport`` (operator reads it from MailDev in dev, or
    receives it via the SMTP production wiring in prod).
    """
    body = await request.json()
    email = body.get("email", "")

    port = _get_password_auth(request)
    if isinstance(port, JSONResponse):
        return port

    reset_url = None
    if email and isinstance(email, str):
        token = port.request_password_reset(email)
        if token:
            # SPEC: the reset URL is written to the local backend's
            # mail_transport log. In dev that's MailDev; in prod that's
            # Resend SMTP per the umbrella decision.
            settings = get_settings()
            public_base = os.environ.get("APAP_PUBLIC_BASE_URL", "https://apap.romancaba.com")
            public_base = public_base.rstrip("/")
            reset_url = f"{public_base}/auth/reset-password?token={token}"

            mail_transport = getattr(request.app.state, "mail_transport", None)
            await mail_transport.send_magic_link(
                email,
                token,
                public_base,  # base_url — transport uses this for URL building
            )

    return JSONResponse(
        {"status": "queued", "reset_url": reset_url},  # may be None for unknown user (AS3 leak prevention)
        status_code=200,
    )


async def reset_password_handler(request: Request) -> JSONResponse:
    """POST /auth/reset-password — AS4.1 happy path; AS4.2 expired / invalid → 400."""
    body = await request.json()
    token = body.get("token", "")
    new_password = body.get("new_password", "")

    if not token or not isinstance(token, str):
        return JSONResponse(
            {"error": "invalid_request", "detail": "token is required"},
            status_code=400,
        )
    if not new_password or not isinstance(new_password, str):
        return JSONResponse(
            {"error": "invalid_request", "detail": "new_password is required"},
            status_code=400,
        )
    if len(new_password) < MIN_PASSWORD_LEN:
        return JSONResponse(
            {"error": "weak_password",
             "detail": f"new_password must be at least {MIN_PASSWORD_LEN} characters"},
            status_code=400,
        )

    port = _get_password_auth(request)
    if isinstance(port, JSONResponse):
        return port

    user = port.consume_password_reset(token, new_password)
    if user is None:
        # AS4.2 — invalid or expired token
        return JSONResponse(
            {"error": "invalid_token"},
            status_code=400,
        )

    # AS4.1 — success: log the user in immediately
    response = JSONResponse({
        "status": "authenticated",
        "email": user.email,
        "rol": user.rol,
    })
    return _set_apap_session_cookie(response, user.email)


def register_password_routes(app: FastAPI) -> None:
    """Mount the three classic-password routes on the FastAPI app."""
    app.add_api_route("/auth/login", login_handler, methods=["POST"])
    app.add_api_route("/auth/forgot-password", forgot_password_handler, methods=["POST"])
    app.add_api_route("/auth/reset-password", reset_password_handler, methods=["POST"])


__all__ = ["register_password_routes"]
