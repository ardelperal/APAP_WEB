"""Magic-link router for the local backend (M3.4, issue #651).

The router mounts under ``/auth`` (was ``/api`` pre-M3.4 path correction) via ``app/core/local_backend/app.py`` and ``app/routes_registry.py``
and serves the two endpoints the login flow expects:

- ``POST /auth/magic/start`` (JSON body ``{"email": "..."}``) mints a
  token via :class:`MagicLinkPort` and asks
  :class:`SMTPMailTransport` to deliver the verify URL. Returns
  ``{"status": "queued"}``. 400 on missing or malformed email.
- ``GET /auth/magic/verify?token=...`` consumes the token, resolves the
  user from the ``usuarios_autorizados`` table (via the
  :class:`AuthUsersPort` seam, issue #917) and redirects to ``/`` with
  the signed ``apap_session`` cookie. The session payload matches the OAuth
  callback contract exactly (``csrf_token``, ``user_id``, ``rol``,
  ``email``, ``is_authorized``) so ``CsrfMiddleware`` accepts form
  writes and audit events / the per-user rate-limit bucket carry the
  real ``user_id``. If the email is not an ACTIVE user in
  ``usuarios_autorizados`` (or the lookup fails), the flow fails
  closed: 302 to ``/unauthorized`` without a session cookie. Because
  the browser holds no session at that point, the auth gate bounces
  its next navigation to ``/login`` — so the user-visible end state of
  the fail-closed path is the login page. On invalid token (unknown /
  expired / used) the route itself redirects to
  ``/login?reason=invalid_or_expired`` without setting any cookie; the
  two outcomes are therefore distinguishable from the network side
  (``/unauthorized`` vs ``/login?reason=...``) and this module does
  NOT claim no-oracle parity between them.

The router is THIN: parsing + guards + delegation only; the SQL
lives in :class:`MagicLinkPortImpl`, the SMTP send lives in
:class:`SMTPMailTransport`, the cookie signing lives in
:mod:`app.core.session`. The handler is bounded by §28's 50-line
budget per route — the start handler fits well under, the verify
handler is at the edge and pushes the cookie construction into a
private helper to stay under the limit.

Hard rules (apap-architecture HR-7, HR-8, HR-9):

- The handler does NOT call :class:`MagicLinkPortImpl` directly; it
  reads ``request.app.state.magic_link_port`` (DI seam).
- The handler does NOT touch ``smtplib``; it delegates to
  ``request.app.state.smtp_transport``.
- Validation (email format) lives in the handler, not the port, so
  the route layer is responsible for the user-facing error message.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.csrf import issue_csrf_to_session
from app.core.data_access import BackendError
from app.core.local_backend.auth_adapter import LocalBackendAuthUsersAdapter
from app.core.local_backend.db import DatabaseError, QueryError
from app.core.logging import log_safe
from app.core.session import write_session

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.domain.auth.user import AuthorizedUser
    from app.core.mail.smtp_transport import SMTPMailTransport
    from app.core.ports.auth_port import AuthUsersPort
    from app.core.ports.magic_link_port import MagicLinkPort


router = APIRouter()

# RFC-5321 "atext" minimal: any non-empty local part + "@" + at least
# one dot in the domain. Sufficient for a single-user-system where
# the canonical email is the only identifier; a future slice can
# swap this for :mod:`email_validator` if the address space grows.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _resolve_auth_users_port(app: FastAPI) -> AuthUsersPort | None:
    """Resolve the :class:`AuthUsersPort` for the verify flow (issue #917).

    Resolution order mirrors :func:`app.core.di.auth_di.get_auth_users_port`:

    1. ``app.state._auth_users_port`` — test override seam.
    2. ``app.state.sql_executor`` — production path wired by BOTH app
       lifespans (``app/main.py`` and the standalone local backend).
    3. ``app.state.local_postgres_executor`` — standalone local-backend
       fallback (M0 attribute name).

    Returns ``None`` when no executor is wired — the caller MUST fail
    closed on ``None`` (no session minted).

    The adapter is the local-backend-package implementation
    (``app.core.local_backend.auth_adapter``): infrastructure →
    infrastructure, so the import stays clean under ``check_layers``
    (the ``app.core.adapters.local_backend`` variant would cross into
    the adapters layer, which is baselined only for ``auth_adapter.py``
    itself).
    """
    override = getattr(app.state, "_auth_users_port", None)
    if override is not None:
        return override
    executor = getattr(app.state, "sql_executor", None) or getattr(
        app.state, "local_postgres_executor", None
    )
    if executor is None:
        return None
    return LocalBackendAuthUsersAdapter(executor)


def _lookup_authorized_user(app: FastAPI, email: str) -> AuthorizedUser | None:
    """Return the ACTIVE user for ``email`` via the auth port, or ``None``.

    ``None`` covers all three fail-closed shapes: no port wired, email
    not in ``usuarios_autorizados`` (the adapter SQL filters
    ``activo = true``), and transport errors — the verify route cannot
    distinguish them and MUST NOT mint a session for any of them
    (issue #917).
    """
    port = _resolve_auth_users_port(app)
    if port is None:
        return None
    try:
        return port.get_user_by_email(email)
    except (BackendError, DatabaseError, QueryError) as exc:
        # Transport failure: fail closed (no session), never 500-leak
        # the backend error into the login redirect chain. Observability
        # (judgment-day JD-B-003): the silent ``return None`` made
        # backend outages indistinguishable from misconfiguration in
        # the logs; emit the error CLASS only — never the token or the
        # email (same PII posture as the surrounding auth events).
        log_safe(
            "auth.magic_link.lookup_failed",
            error_class=type(exc).__name__,
        )
        return None


def _unauthorized_redirect() -> Response:
    """Generic 302 to ``/unauthorized`` WITHOUT a session cookie.

    Fail-closed response for an inactive/unknown email or a failed
    lookup. This is NOT a no-oracle twin of the invalid-token redirect:
    the invalid-token path returns ``/login?reason=invalid_or_expired``
    directly, while this response's location is ``/unauthorized``. The
    user-visible end state converges on the login page either way —
    with no session cookie the browser's next navigation is bounced to
    ``/login`` by the auth gate — but the raw responses differ and this
    module does not pretend otherwise (judgment-day JD-A-003/JD-B-007).
    """
    return Response(status_code=302, headers={"location": "/unauthorized"})


def _build_session_payload(user: AuthorizedUser) -> dict[str, object]:
    """Project the verified user to the session payload shape (issue #917).

    Matches the contract :mod:`app.core.auth_flow` writes from the
    OAuth callback (``issue_csrf_to_session`` over ``{email, user_id,
    rol, is_authorized}``). The magic-link flow IS the authorization:
    the user clicked a single-use, 30-minute-TTL token in their inbox,
    which is at least as strong as the OAuth callback's
    ``is_authorized=True`` flag (the OAuth callback also has no
    password check — it trusts the Google account). Carrying
    ``csrf_token`` unblocks form writes for the whole session;
    ``user_id`` feeds the ``auth.denied`` audit events and the
    per-user ``write_user`` rate-limit bucket. The DB revalidation
    in :func:`app.core.di.auth_dependencies_session_di.require_authorized_user`
    still runs on every subsequent request via the auth_users table; if
    the user has been deactivated since the link was minted, the next
    request gets ``/unauthorized``.
    """
    return issue_csrf_to_session(
        {
            "email": user.email,
            "user_id": user.id,
            "rol": user.rol.value,
            "is_authorized": True,
        }
    )


def _set_apap_session_cookie(response: Response, payload: dict[str, object], secret: str) -> None:
    """Sign the session payload and attach the ``apap_session`` cookie.

    Flags match :func:`app.core.session.clear_session_cookie_params`
    (``httponly=True``, ``secure=True``) so the cookie cannot be read
    from JS. ``samesite="lax"`` (not strict) is required here because
    the user arrives at ``/auth/magic/verify`` from a cross-site
    context (their email client); strict would silently drop the cookie
    on that top-level redirect and the user would land on ``/login``
    despite the token being valid. The CSRF defense-in-depth is
    preserved by :class:`CsrfMiddleware` which validates the CSRF token
    on every non-safe request; the auth layer also enforces session
    presence for protected routes.
    """
    response.set_cookie(
        key="apap_session",
        value=write_session(payload, secret=secret),
        max_age=60 * 60 * 24 * 7,  # 7 days, matches _SESSION_MAX_AGE_SECONDS
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


@router.post("/auth/magic/start")
async def start_magic_link(request: Request, payload: dict[str, object]) -> dict:
    """Mint a magic-link token and queue the verify email.

    The handler reads the canonical email from the body, validates the
    shape (cheap, fast — never raises on a malformed input), and
    delegates persistence + delivery to the port + transport on
    ``app.state``. The 200 envelope is deliberately minimal
    (``{"status": "queued"}``) so the frontend can show a generic
    "we sent you a link" message without learning whether the email
    exists in the user table — the magic-link flow does not
    distinguish "authorized" from "unknown" emails.
    """
    raw_email = payload.get("email")
    if not isinstance(raw_email, str) or not _EMAIL_RE.match(raw_email.strip()):
        raise HTTPException(status_code=400, detail={"error": "invalid_email"})
    email = raw_email.strip().lower()

    port: MagicLinkPort = request.app.state.magic_link_port
    transport: SMTPMailTransport = request.app.state.smtp_transport
    base_url: str = request.app.state.public_base_url

    raw_token = port.create_token(email)
    verify_url = f"{base_url}/auth/magic/verify?token={raw_token}"
    transport.send(
        to_addr=email,
        subject="Tu enlace de acceso a APAP",
        body=(
            "Hola,\n\n"
            "Recibimos una solicitud de inicio de sesión para tu cuenta en APAP.\n"
            "Pulsa el siguiente enlace para entrar (caduca en 30 minutos, "
            "solo se puede usar una vez):\n\n"
            f"    {verify_url}\n\n"
            "Si no has solicitado este enlace, puedes ignorar este mensaje.\n\n"
            "— Equipo APAP Alcalá de Henares\n"
        ),
    )
    return {"status": "queued"}


@router.get("/auth/magic/verify")
async def verify_magic_link(
    request: Request,
    response: Response,
    token: Annotated[str, Query(...)],
) -> Response:
    """Consume the token, set the session cookie, redirect home.

    The handler reads the port + secret from ``app.state``. On success
    it resolves the ACTIVE user for the token's email via the
    :class:`AuthUsersPort` seam (issue #917) and returns a 302 to ``/``
    with the ``apap_session`` cookie attached. If the email is not an
    active user (or the lookup fails) it redirects to
    ``/unauthorized`` WITHOUT a cookie — fail closed. On token failure
    (unknown / used / expired) it redirects to
    ``/login?reason=invalid_or_expired`` without setting a cookie — the
    route never tells the caller WHY the token failed (no oracle for
    token validity).
    """
    port: MagicLinkPort = request.app.state.magic_link_port
    secret: str = request.app.state.session_secret

    email = port.consume_token(token)
    if email is None:
        # 302 (not 400) so the user lands back on /login with a
        # generic reason; the route does not echo whether the token
        # was unknown vs expired vs already used.
        return Response(
            status_code=302,
            headers={"location": "/login?reason=invalid_or_expired"},
        )

    # Fail closed on unknown email / transport failure (issue #917):
    # no session cookie, generic /unauthorized redirect.
    user = _lookup_authorized_user(request.app, email)
    if user is None:
        return _unauthorized_redirect()

    # Build the redirect response, then attach the cookie before
    # returning — set_cookie mutates ``response.headers`` in place.
    redirect = Response(
        status_code=302,
        headers={"location": "/"},
    )
    _set_apap_session_cookie(redirect, _build_session_payload(user), secret)
    # Mirror the OAuth callback's ``auth.login`` event (app.core.auth_flow)
    # so magic-link logins appear in the same audit stream. ``email`` is
    # redacted by ``log_safe``'s closed PII list.
    log_safe("auth.login", email=user.email, user_id=user.id)
    return redirect


__all__ = ["router"]
