"""Magic-link router for the local backend (M3.4, issue #651).

The router mounts under ``/api`` via ``app/core/local_backend/app.py``
and serves the two endpoints the login flow expects:

- ``POST /api/magic/start`` (JSON body ``{"email": "..."}``) mints a
  token via :class:`MagicLinkPort` and asks
  :class:`SMTPMailTransport` to deliver the verify URL. Returns
  ``{"status": "queued"}``. 400 on missing or malformed email.
- ``GET /api/magic/verify?token=...`` consumes the token. On success
  redirects to ``/`` and sets the signed ``apap_session`` cookie. On
  failure (unknown / expired / used token) redirects to
  ``/login?reason=invalid_or_expired`` without setting any cookie.

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

from app.core.session import write_session

if TYPE_CHECKING:
    from app.core.mail.smtp_transport import SMTPMailTransport
    from app.core.ports.magic_link_port import MagicLinkPort


router = APIRouter()

# RFC-5321 "atext" minimal: any non-empty local part + "@" + at least
# one dot in the domain. Sufficient for a single-user-system where
# the canonical email is the only identifier; a future slice can
# swap this for :mod:`email_validator` if the address space grows.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _build_session_payload(email: str) -> dict[str, object]:
    """Project the verified email to the session payload shape.

    Matches the contract :mod:`app.core.auth_flow` writes from the
    OAuth callback. ``is_authorized`` is read live from the DB on
    each request via :func:`app.core.auth_dependencies.require_authorized_user`
    so we deliberately do NOT carry it in the cookie; the DB
    revalidation is the source of truth (issue #143).
    """
    return {"email": email}


def _set_apap_session_cookie(response: Response, email: str, secret: str) -> None:
    """Sign the session payload and attach the ``apap_session`` cookie.

    Flags match :func:`app.core.session.clear_session_cookie_params`
    (``httponly=True``, ``secure=True``, ``samesite="strict"``) so
    the cookie cannot be read from JS and the strict SameSite blocks
    cross-site POSTs (CSRF defense-in-depth, §10 / PR-5B).
    """
    response.set_cookie(
        key="apap_session",
        value=write_session(_build_session_payload(email), secret=secret),
        max_age=60 * 60 * 24 * 7,  # 7 days, matches _SESSION_MAX_AGE_SECONDS
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )


@router.post("/magic/start")
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
    verify_url = f"{base_url}/api/magic/verify?token={raw_token}"
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


@router.get("/magic/verify")
async def verify_magic_link(
    request: Request,
    response: Response,
    token: Annotated[str, Query(...)],
) -> Response:
    """Consume the token, set the session cookie, redirect home.

    The handler reads the port + secret from ``app.state``. On
    success it returns a 302 to ``/`` with the ``apap_session``
    cookie attached. On any failure (unknown / used / expired) it
    redirects to ``/login?reason=invalid_or_expired`` without
    setting a cookie — the route never tells the caller WHY the
    token failed (no oracle for token validity).
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

    # Build the redirect response, then attach the cookie before
    # returning — set_cookie mutates ``response.headers`` in place.
    redirect = Response(
        status_code=302,
        headers={"location": "/"},
    )
    _set_apap_session_cookie(redirect, email, secret)
    return redirect


__all__ = ["router"]
