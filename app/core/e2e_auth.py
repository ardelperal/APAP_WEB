"""E2E test-only OAuth mock (issue #598).

The production app refuses to mint a session without Google OAuth
credentials configured: ``/login`` returns 503 and ``/auth/google``
raises ``OAuthNotConfiguredError`` whenever ``Settings.google_client_id``
is empty. For Playwright E2E tests this blocks flow coverage
entirely — every authenticated route (admin, animals, adopciones)
returns a redirect to ``/login`` and the test has no way past it.

This module closes the loop by registering a single test-only
route, ``POST /e2e/login``, that mints a session directly when:

1. ``Settings.e2e_auth_enabled`` is True (the route is **not
   registered** otherwise — production deployments must leave
   this off, in which case the existing 503 behaviour from
   :mod:`app.core.auth_flow` stands),
2. The ``X-E2E-Secret`` request header matches ``Settings.e2e_auth_secret``
   (constant-time comparison, defence against timing-leak probes),
3. The email is one the operator opted in to via
   ``Settings.e2e_auth_default_email`` or ``?email=…``.

The session payload is identical in shape to the OAuth callback's
output (``email``, ``rol``, ``user_id``, ``is_authorized=True``,
``csrf_token``) and the in-process auth cache is pre-populated so
:func:`app.core.auth_dependencies.require_authorized_user` accepts
the cookie without consulting the database — the mock is therefore
independent of the ``usuarios_autorizados`` seed.

This is a **test-only** surface. The route name (``/e2e/...``)
and the gating (env-var + secret header) are deliberately loud so
nothing in production routes accidentally points at it.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.auth_cache import set_cached_auth
from app.core.config import get_settings
from app.core.csrf import generate_csrf_token
from app.core.session import (
    session_cookie_name,
    write_session,
)

# Fixed UUID for the mock user — deterministic so log lines / session
# payloads are stable across E2E runs and so a future change to the
# UUID does not accidentally drift past the database seed.
MOCK_USER_ID: str = "00000000-0000-0000-0000-0000000000e2e"

# Default role the mock mints. Matches the ``developer`` role used
# by the legacy admin route — the only role with full backend
# access, which is what E2E flow tests want.
MOCK_USER_ROL: str = "developer"


def _mock_session_payload(*, email: str, csrf_token: str) -> dict[str, object]:
    """Build the session payload the OAuth callback would have minted.

    Mirrors :func:`app.core.auth_flow.callback` exactly so the cookie
    shape is identical: ``email``, ``rol``, ``user_id``,
    ``is_authorized=True``, ``csrf_token``. The auth cache call below
    is what makes the middleware accept the cookie without a DB
    round-trip.
    """
    return {
        "email": email,
        "rol": MOCK_USER_ROL,
        "user_id": MOCK_USER_ID,
        "is_authorized": True,
        "csrf_token": csrf_token,
    }


def register_e2e_auth_routes(app: FastAPI) -> None:
    """Register the ``/e2e/login`` route when the mock is enabled.

    No-op when ``Settings.e2e_auth_enabled`` is False — the route is
    not registered, so a probe to ``/e2e/login`` in production
    receives FastAPI's default 404 (no route matched) rather than a
    503 that could be confused with the OAuth-unconfigured 503.
    """
    settings = get_settings()
    if not settings.e2e_auth_enabled:
        return

    @app.get("/e2e/login")
    def _e2e_login(
        email: Annotated[
            str | None,
            Query(
                description=(
                    "Email to mint the session for. Defaults to "
                    "Settings.e2e_auth_default_email when omitted."
                )
            ),
        ] = None,
        x_e2e_secret: Annotated[
            str | None,
            Header(
                alias="X-E2E-Secret",
                description=(
                    "Shared secret that gates the mock route. "
                    "Production deployments MUST leave "
                    "Settings.e2e_auth_enabled=False so this header "
                    "is never consulted."
                ),
            ),
        ] = None,
    ) -> JSONResponse:
        """Mint a signed session cookie for the configured E2E user.

        Returns ``{"authenticated": true, "email": ...}`` with the
        ``apap_session`` cookie set on success. The auth cache is
        pre-populated so the very next request from the test client
        is authorized without a DB round-trip.

        GET (not POST) on purpose: the mock is test-only and the
        X-E2E-Secret header is a non-guessable shared secret that
        browsers will NOT send cross-origin, so the route does not
        need the CSRF defence that applies to cookie-authenticated
        POSTs. Routing through GET also keeps the CSRF middleware's
        safe-methods short-circuit out of the way, so the test
        client does not have to send a ``csrf_token`` header that
        it does not yet have (the token comes back in the
        response).
        """
        expected_secret = settings.e2e_auth_secret
        if not expected_secret:
            # The env-var is set but the secret is empty — treat
            # that as a configuration bug, not as "disable auth".
            raise HTTPException(
                status_code=503,
                detail=(
                    "e2e_auth_enabled=True but e2e_auth_secret is "
                    "empty; the mock cannot accept any request."
                ),
            )
        if x_e2e_secret is None or not hmac.compare_digest(
            x_e2e_secret, expected_secret
        ):
            raise HTTPException(
                status_code=401,
                detail="X-E2E-Secret missing or invalid.",
            )

        target_email = (email or settings.e2e_auth_default_email).strip()
        if not target_email:
            raise HTTPException(
                status_code=400,
                detail=(
                    "email query param is empty and "
                    "e2e_auth_default_email is unset."
                ),
            )

        csrf_token = generate_csrf_token()
        payload = _mock_session_payload(email=target_email, csrf_token=csrf_token)
        # Pre-populate the in-process auth cache so the very next
        # request the test makes (and any subsequent request from
        # the same browser context) bypasses the DB lookup. The
        # middleware reads from this cache on every authorized
        # request.
        set_cached_auth(
            target_email,
            is_authorized=True,
            rol=MOCK_USER_ROL,
        )

        session_token = write_session(payload, secret=settings.session_secret)

        response = JSONResponse(
            {
                "authenticated": True,
                "email": target_email,
                "user_id": MOCK_USER_ID,
                "rol": MOCK_USER_ROL,
                "csrf_token": csrf_token,
            }
        )
        # Cookie parameters mirror the OAuth callback's
        # ``apap_session`` minting in ``auth_flow.callback`` so the
        # test client ends up with an indistinguishable cookie.
        response.set_cookie(
            session_cookie_name(),
            session_token,
            path="/",
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=60 * 60 * 24 * 7,
        )
        return response
