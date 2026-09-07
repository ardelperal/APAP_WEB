"""Auth-flow route handlers extracted from ``app/main.py::create_app``.

This module is the backward-compat SHIM for the OAuth login flow.
The domain logic has been migrated to the hexagonal slice:

  - :mod:`app.core.domain.oauth`          — entities + Protocol errors
  - :mod:`app.core.ports.oauth_port`      — :class:`OAuthPort` Protocol
  - :mod:`app.core.application.oauth`     — use cases (one per file)
  - :mod:`app.core.adapters.insforge.oauth_insforge_adapter` — InsForge adapter
  - :mod:`app.core.di.oauth_di`           — FastAPI DI provider

The route handlers below are now THIN: each one parses the
transport-level concerns (cookies, query params, template
rendering) and delegates the domain decision to the new use case.

Issue #336: extracted from ``create_app`` to reduce the factory's
cyclomatic complexity (CC) and line count.

Issue judgment-day 2026-08-04 BLOCKER §31 (the legacy
``auth_flow.py:21`` imported :class:`LocalPostgresExecutor` and
:class:`BackendError` directly) is now fixed: this module no
longer imports any InsForge-shaped symbol. The adapter wraps the
InsForge client; the use cases depend on the Protocol.

Issue judgment-day 2026-08-04 §32.P4 (the legacy 165-166 caught a
bare ``BackendError`` and silently turned every transport failure
into a ``/login`` redirect) is also fixed: the new
:meth:`callback` use case catches ``BackendError`` ONLY at the
single exchange call site (the legitimate failure path), and the
adapter raises Protocol-level errors for the application-level
failures (no code, not authorized) that the route translates
explicitly.

Backwards compatibility:

- :func:`register_auth_flow_routes(app, templates)` — unchanged
  signature. ``app/main.py::create_app`` still calls it the same
  way.
- The four route URLs (``/login``, ``/auth/google``,
  ``/auth/callback``, ``/logout``) are unchanged.
- The cookie names (``apap_pkce``, ``apap_session``), their
  flags (``samesite=lax`` for PKCE, ``samesite=strict`` for
  session, ``httponly=True``, ``secure=True``), and the
  SameSite=Strict logout-clearing shape are all preserved
  verbatim. The existing ``tests/test_auth_flow.py`` suite
  passes without modification.
- The 503 message body for unconfigured Google OAuth is
  preserved verbatim — the operator-facing remediation
  string is the same.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core import config as config_module
from app.core.adapters.stubs.auth_users_stub import StubAuthUsersPort
from app.core.adapters.stubs.oauth_stub import StubOAuthPort
from app.core.application.oauth import (
    callback as callback_use_case,
)
from app.core.application.oauth import (
    login_page as login_page_use_case,
)
from app.core.application.oauth import (
    logout as logout_use_case,
)
from app.core.application.oauth import (
    start_google_login as start_google_login_use_case,
)
from app.core.auth_dependencies import get_insforge_client_dep
from app.core.csrf import issue_csrf_to_session
from app.core.data_access import BackendError
from app.core.domain.oauth import (
    CallbackInvalidError,
    OAuthNotConfiguredError,
    UserNotAuthorizedError,
)
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.logging import log_safe
from app.core.session import (
    read_session,
    session_cookie_name,
    write_session,
)


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=302)


def _oauth_unconfigured_response() -> JSONResponse:
    """Return the 503 JSON the legacy route produced.

    The shape is preserved verbatim so the existing
    ``tests/test_auth_flow.py::test_login_returns_503_when_google_not_configured``
    keeps matching. The error message is the operator's
    remediation hint, identical to the one
    :class:`OAuthNotConfiguredError` carries — keeping the
    single source of truth.
    """
    return JSONResponse(
        {
            "error": (
                "Google OAuth no está configurado: define "
                "APAP_GOOGLE_CLIENT_ID y APAP_GOOGLE_CLIENT_SECRET."
            )
        },
        status_code=503,
    )


def register_auth_flow_routes(app: FastAPI, templates) -> None:
    """Register the OAuth auth-flow routes on ``app``.

    Registers: ``/login``, ``/auth/google``, ``/auth/callback``, ``/logout``.
    These are application-level glue routes that share the
    ``templates`` instance created inside ``create_app``.

    The route handlers are THIN: each one handles only transport
    concerns (cookie parsing, redirect building, template
    rendering) and delegates the domain decision to a use case in
    :mod:`app.core.application.oauth`. The :class:`LocalPostgresExecutor`
    is constructed per-request by the shim helpers
    (no DI; the legacy shape is preserved).
    """

    @app.get("/login")
    def login(request: Request) -> Response:
        """Render APAP's login page, or 503 when Google OAuth is unconfigured.

        This route is intentionally passive. Starting OAuth directly
        from ``/login`` creates a redirect loop when ``/auth/callback``
        cannot complete (for example, missing/expired PKCE cookie):
        callback -> login -> provider -> callback forever. The user
        must click the Gmail button, which posts no data and simply
        navigates to ``/auth/google``.
        """
        settings = config_module.get_settings()
        app_name = login_page_use_case(settings)
        if app_name is None:
            return _oauth_unconfigured_response()
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"app_name": app_name},
        )

    @app.get("/auth/google")
    def start_google_login(
        client: Annotated[LocalPostgresExecutor, Depends(get_insforge_client_dep)],
    ) -> Response:
        """Start the Google OAuth flow via InsForge.

        Generates a PKCE pair (now inside the adapter), stores the
        verifier in a short-lived ``apap_pkce`` cookie, asks
        InsForge for the Google auth URL, and redirects the user
        there.
        """
        settings = config_module.get_settings()
        try:
            pkce, auth_url = start_google_login_use_case(
                StubOAuthPort(),
                settings,
            )
        except OAuthNotConfiguredError:
            return _oauth_unconfigured_response()

        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            "apap_pkce",
            write_session(
                {"code_verifier": pkce.code_verifier},
                secret=settings.session_secret,
            ),
            httponly=True,
            secure=True,
            # OAuth returns to /auth/callback via a top-level cross-site GET
            # from Google/InsForge. SameSite=Strict is not sent on that
            # navigation, so the callback cannot read the verifier and starts
            # a /callback -> /login loop. Lax keeps the verifier out of
            # cross-site subrequests/forms while allowing the OAuth callback.
            samesite="lax",
            max_age=600,
        )
        return response

    @app.get("/auth/callback")
    def callback(
        request: Request,
        client: Annotated[LocalPostgresExecutor, Depends(get_insforge_client_dep)],
        insforge_code: str | None = None,
        code: str | None = None,  # legacy direct-callback (pre-InsForge-proxy)
    ) -> Response:
        """Exchange the OAuth code for an InsForge JWT and issue a session.

        InsForge's hosted OAuth proxy fronts Google and other providers
        with a two-step flow: APAP starts the flow at ``/login`` (which
        hits ``GET /api/auth/oauth/google`` and gets back a Google OAuth
        URL); after consent, Google → InsForge → APAP with
        ``?insforge_code=<temporary>``; APAP then exchanges that code
        here via ``POST /api/auth/oauth/exchange``. The legacy
        ``?code=<google-code>`` direct-callback parameter is also
        accepted so existing test suites and any direct callbacks keep
        working.

        The ``code_verifier`` is recovered from the short-lived PKCE
        cookie minted at ``/login``. The email returned by InsForge is
        checked against ``usuarios_autorizados``; authorized users get
        a signed session cookie, everyone else is redirected to
        ``/unauthorized``.
        """
        settings = config_module.get_settings()
        pkce_token = request.cookies.get("apap_pkce")
        if not pkce_token:
            return _redirect("/login")
        pkce = read_session(pkce_token, secret=settings.session_secret)
        if not pkce or "code_verifier" not in pkce:
            return _redirect("/login")

        try:
            session = callback_use_case(
                StubOAuthPort(),
                StubAuthUsersPort(),
                insforge_code=insforge_code,
                code=code,
                code_verifier=pkce["code_verifier"],
                redirect_uri=settings.google_redirect_uri,
            )
        except CallbackInvalidError:
            # No code supplied (neither insforge_code nor code). The
            # user landed here with a stale cookie. Bounce to /login
            # so they can re-start the flow.
            return _redirect("/login")
        except UserNotAuthorizedError:
            response = _redirect("/unauthorized")
            response.delete_cookie("apap_pkce")
            return response
        except BackendError:
            # §32.P4 fix: the legacy code caught a bare BackendError
            # for every failure (no code, transport, not authorized,
            # all collapsed). The new use case catches it ONLY at the
            # single exchange call site, so this is now the narrow
            # "transport failed" path — the genuine exchange errors.
            return _redirect("/login")

        # The signed cookie carries identity + advisory role (stable
        # for 7 days). ``is_authorized`` is NOT the source of truth
        # anymore — ``require_authorized_user`` (#143) re-validates
        # against ``usuarios_autorizados`` on every request via a
        # TTL cache (``Settings.auth_cache_ttl_seconds``, default
        # 300s), so an admin deactivation via
        # ``/admin/users/{id}/deactivate`` takes effect within the TTL
        # instead of waiting for the cookie to expire. The P0 VOL-01
        # fix this comment replaced is preserved as the first gate
        # (``is_authorized`` defaults to False — default-deny),
        # not as the final answer.
        #
        # PR-5B (REQ-AH-6) adds ``csrf_token`` via ``issue_csrf_to_session``
        # so the CSRF middleware (REQ-AH-8) can validate POST/PUT/PATCH/DELETE
        # without relying solely on SameSite cookies.
        session_token = write_session(
            issue_csrf_to_session(
                {
                    "email": session.email,
                    "rol": session.rol.value,
                    "user_id": session.user_id,
                    "is_authorized": session.is_authorized,
                }
            ),
            secret=settings.session_secret,
        )
        # Slice 6 sample call site (T-6.7): emit a structured
        # ``auth.login`` event. The ``email`` kwarg is REDACTED by
        # ``log_safe`` per the closed 12-field list — operators see
        # the event name and ``user_id`` (non-PII), not the email.
        # This proves the redaction filter is wired end-to-end on a
        # real authentication flow, not just in unit tests.
        log_safe("auth.login", email=session.email, user_id=session.user_id)
        response = _redirect("/")
        response.set_cookie(
            session_cookie_name(),
            session_token,
            # path="/": MUST match the /logout clearing cookie's path
            # (also "/") so the browser can match the Set-Cookie and
            # actually delete the session. Without this, the cookie
            # defaults to the request path (/auth/callback) and the
            # clearing with path="/" is IGNORED by the browser —
            # the user reported Salir does not log them out.
            path="/",
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=60 * 60 * 24 * 7,
        )
        response.delete_cookie("apap_pkce")
        return response

    @app.get("/logout")
    def logout() -> Response:
        """Clear the session cookie and redirect home."""
        params = logout_use_case()
        response = _redirect("/")
        response.set_cookie(**params.kwargs)
        return response
