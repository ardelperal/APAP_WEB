"""Auth-flow route handlers extracted from ``app/main.py::create_app``.

These handlers (, ``start_google_login``, ``callback``, ``logout``) are
application-level glue — they share the ``templates`` instance and the
``settings`` singleton — so they live here rather than in a domain
module. ``create_app`` imports and registers them.

Issue #336: extracted from ``create_app`` to reduce the factory's
cyclomatic complexity (CC) and line count.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.core import config as config_module
from app.core.auth import get_user_by_email
from app.core.auth_dependencies import get_insforge_client_dep as get_insforge_client
from app.core.csrf import issue_csrf_to_session
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.pkce import generate_pkce_pair
from app.core.session import (
    clear_session_cookie_params,
    read_session,
    session_cookie_name,
    write_session,
)


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=302)


def register_auth_flow_routes(app: FastAPI, templates) -> None:
    """Register the OAuth auth-flow routes on ``app``.

    Registers: ``/login``, ``/auth/google``, ``/auth/callback``, ``/logout``.
    These are application-level glue routes that share the ``templates``
    instance created inside ``create_app``.
    """

    @app.get("/login")
    def login(request: Request) -> Response:
        """Render APAP's login page.

        This route is intentionally passive. Starting OAuth directly from
        ``/login`` creates a redirect loop when ``/auth/callback`` cannot
        complete (for example, missing/expired PKCE cookie): callback -> login
        -> provider -> callback forever. The user must click the Gmail button,
        which posts no data and simply navigates to ``/auth/google``.
        """
        settings = config_module.get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            return JSONResponse(
                {
                    "error": (
                        "Google OAuth no está configurado: define "
                        "APAP_GOOGLE_CLIENT_ID y APAP_GOOGLE_CLIENT_SECRET."
                    )
                },
                status_code=503,
            )
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"app_name": settings.app_name},
        )

    @app.get("/auth/google")
    def start_google_login(
        client: Annotated[InsForgeClient, Depends(get_insforge_client)],
    ) -> Response:
        """Start the Google OAuth flow via InsForge.

        Generates a PKCE pair, stores the verifier in a short-lived
        ``apap_pkce`` cookie, asks InsForge for the Google auth URL
        and redirects the user there.
        """
        settings = config_module.get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            return JSONResponse(
                {
                    "error": (
                        "Google OAuth no está configurado: define "
                        "APAP_GOOGLE_CLIENT_ID y APAP_GOOGLE_CLIENT_SECRET."
                    )
                },
                status_code=503,
            )

        code_verifier, code_challenge = generate_pkce_pair()
        auth_url = client.start_google_oauth(
            settings.google_redirect_uri, code_challenge
        )

        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            "apap_pkce",
            write_session(
                {"code_verifier": code_verifier}, secret=settings.session_secret
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
        client: Annotated[InsForgeClient, Depends(get_insforge_client)],
        insforge_code: Annotated[str | None, Query()] = None,
        code: Annotated[str | None, Query()] = None,  # legacy direct-callback (pre-InsForge-proxy)
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
        # lazy-import: avoids circular import with app.core.auth
        from app.core.logging import log_safe

        pkce_token = request.cookies.get("apap_pkce")
        if not pkce_token:
            return _redirect("/login")
        pkce = read_session(pkce_token, secret=settings.session_secret)
        if not pkce or "code_verifier" not in pkce:
            return _redirect("/login")

        try:
            if insforge_code:
                exchange = client.exchange_insforge_oauth_code(
                    insforge_code=insforge_code,
                    code_verifier=pkce["code_verifier"],
                )
            elif code:
                exchange = client.exchange_google_oauth_code(
                    code=code,
                    code_verifier=pkce["code_verifier"],
                    redirect_uri=settings.google_redirect_uri,
                )
            else:
                return _redirect("/login")
        except InsForgeError:
            return _redirect("/login")

        user = get_user_by_email(client, exchange.user.email)
        if not user:
            response = _redirect("/unauthorized")
            response.delete_cookie("apap_pkce")
            return response

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
                    "email": user["email"],
                    "rol": user["rol"],
                    "user_id": user["id"],
                    "is_authorized": bool(user.get("activo", False)),
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
        log_safe("auth.login", email=user["email"], user_id=user["id"])
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
        response = _redirect("/")
        response.set_cookie(**clear_session_cookie_params())
        return response
