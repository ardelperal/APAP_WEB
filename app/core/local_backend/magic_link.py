"""Magic-link router for the local backend (M3.4, issue #651).

The router mounts under ``/auth`` (was ``/api`` pre-M3.4 path correction) via ``app/core/local_backend/app.py`` and ``app/routes_registry.py``
and serves the two endpoints the login flow expects:

- ``POST /auth/magic/start`` (JSON body ``{"email": "..."}``) mints a
  token via :class:`MagicLinkPort` and asks
  :class:`SMTPMailTransport` to deliver the verify URL. Returns
  ``{"status": "queued"}``. 400 on missing or malformed email.
- ``GET /auth/magic/verify?token=...&state=...`` consumes the token,
  resolves the user from the ``usuarios_autorizados`` table (via the
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

Login CSRF (issue #1004, JD-B-010 of #917): a verify GET set-cookies
the session, so the bare ``token`` URL was a bearer capability an
attacker could hand to a victim to force the attacker's session into
the victim's browser. Every token minted by ``/auth/magic/start`` is
now bound server-side to a random single-use ``state`` value embedded
in the emailed verify URL (see :func:`_issue_state` for the storage
decision) AND to the initiating browser via a ``apap_magic_state``
cookie (product decision of #1004, round-1 fix). Verify requires the
exact ``state`` in the URL AND a cookie equal to it (timing-safe
comparison) BEFORE consuming the token: missing / wrong / expired /
replayed state gets the same no-oracle
``/login?reason=invalid_or_expired`` redirect with the token NOT
consumed, so the binding cannot be probed without burning a
legitimately received URL.

Browser binding: the emailed URL carries both secrets (token and
state), so the URL alone is still a bearer capability — the cookie is
what makes it non-forwardable. ``/auth/magic/start`` set-cookies
``apap_magic_state`` (HttpOnly, Secure, SameSite=Lax, Path=/auth/magic,
same TTL as the state binding) in the browser that requested the
link; ``/auth/magic/verify`` demands that cookie. A URL forwarded to
a DIFFERENT browser (the login-CSRF attack) fails closed there, and
the attacker cannot plant the cookie in the victim's browser because
cookies are only set by responses to requests the victim's browser
itself made. ACCEPTED LIMITATION (operator decision, issue #1004):
the link is NOT portable across devices — a user who requests the
link on their phone and opens it on their laptop gets the fail-closed
redirect and must re-request the link from the target device. The
cookie TTL matches the state TTL so both halves of the binding expire
together (see :mod:`app.core.local_backend.state_cookie` for the
cookie contract).

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

import hashlib
import hmac
import re
import secrets
import time
from typing import TYPE_CHECKING, Annotated, NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.csrf import issue_csrf_to_session
from app.core.data_access import BackendError
from app.core.local_backend.auth_adapter import LocalBackendAuthUsersAdapter
from app.core.local_backend.db import DatabaseError, QueryError
from app.core.local_backend.state_cookie import (
    expire_state_cookie,
    set_state_cookie,
    state_cookie_matches,
)
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

_STATE_TTL_SECONDS = 1800
"""Fallback TTL of the verify-state binding.

The EFFECTIVE TTL is derived from the wired port's token TTL at
binding creation (see :func:`_state_ttl_for`) so a state can never
outlive the token it authorises; this constant is the fallback for a
port that does not expose its TTL and the value unit tests pin the
equality against (issue #1004, JD-B-005).
"""


class _StateBinding(NamedTuple):
    """Server-side binding between a single-use ``state`` value and the
    magic-link token it authorises (issue #1004).

    Storage decision: an in-process store on ``app.state``, not the
    ``MagicLinkPort`` store. Reusing the port would mean persisting the
    state as a second ``magic_link_tokens`` row, but the port does not
    enforce ``purpose`` — a state value stored there would be
    consumable as a LOGIN token at ``?token=<state>``, turning the
    state into a second independent login credential in the same URL.
    The port also cannot carry an ephemeral non-credential secret
    without adapter + schema changes (outside this slice). An
    in-process binding keeps the state a NON-credential: it is useless
    without the token it is bound to. Restarting the process loses
    outstanding bindings, which fails closed (verify redirects to the
    login page; the user requests a fresh link)."""

    token_hash: str
    """SHA-256 hex of the raw token this state authorises."""

    expires_at: float
    """``time.monotonic()`` deadline for the binding."""


def _state_store(app: FastAPI) -> dict[str, _StateBinding]:
    """Return the per-app state store, creating it lazily on first use.

    Lazy creation keeps the wiring inside this module: neither
    ``app/main.py`` nor the standalone backend lifespan needs a new
    line, and every app instance gets an isolated store (tests included).
    """
    store = getattr(app.state, "_magic_link_states", None)
    if store is None:
        store = {}
        app.state._magic_link_states = store
    return store


def _state_ttl_for(port: MagicLinkPort) -> int:
    """Return the state-binding TTL derived from the wired port's token TTL.

    Coupling (issue #1004, JD-B-005): the state and the token it
    authorises must expire together, so the TTL is read from the port
    at binding creation instead of being an independent constant. The
    ``MagicLinkPort`` protocol does not expose a TTL, so this reads the
    concrete adapter's ``_ttl`` attribute (set by ``MagicLinkPortImpl``
    from the lifespan wiring) with a fallback to ``_STATE_TTL_SECONDS``
    for any port that does not carry one. Equality with the adapter
    default is pinned in ``tests/test_magic_link_state_ttl.py``.
    """
    ttl = getattr(port, "_ttl", None)
    if isinstance(ttl, int) and ttl > 0:
        return ttl
    return _STATE_TTL_SECONDS


def _issue_state(app: FastAPI, raw_token: str, *, ttl_seconds: int = _STATE_TTL_SECONDS) -> str:
    """Bind a fresh single-use ``state`` to ``raw_token`` and return it.

    The value is 256 bits of URL-safe entropy, embedded in the emailed
    verify URL (issue #1004). Only the token HASH is stored — the raw
    token never touches the binding, mirroring the port's "only the
    SHA-256 is persisted" posture. Expired bindings are pruned on each
    issue so the store cannot grow without bound. The TTL derives from
    the wired port's token TTL (see :func:`_state_ttl_for`).
    """
    store = _state_store(app)
    now = time.monotonic()
    for expired in [key for key, binding in store.items() if binding.expires_at <= now]:
        del store[expired]
    state = secrets.token_urlsafe(32)
    store[state] = _StateBinding(
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=now + ttl_seconds,
    )
    return state


def _consume_state(app: FastAPI, state: str | None, raw_token: str) -> bool:
    """Return ``True`` only for the ONE valid use of ``state`` on ``raw_token``.

    Single-use by construction: the binding is popped BEFORE it is
    judged, so a failed verify (expired, wrong token) also consumes the
    state and a replay always finds the store empty. Fail closed on
    every miss: missing value, unknown value, expired binding, or a
    state presented over a different token than the one it was minted
    for (the token-hash comparison is timing-safe via
    ``hmac.compare_digest``; the state key itself is 256-bit random,
    so its dict lookup is not a timing oracle worth hardening).
    """
    if not state:
        return False
    binding = _state_store(app).pop(state, None)
    if binding is None:
        return False
    if binding.expires_at <= time.monotonic():
        return False
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return hmac.compare_digest(binding.token_hash, token_hash)


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


def _consume_bound_state(
    request: Request, port: MagicLinkPort, state: str | None, token: str
) -> str | None:
    """Spend the browser binding, the single-use state and the token.

    Guard order and one-shot semantics of the verify flow (issue
    #1004): the URL state and the state cookie must both be present
    and equal (a mismatch never burns the server-side binding), then
    the single-use state (a state failure never burns the token), then
    the token. Returns the token's email, or ``None`` on any failure —
    the caller answers every failure with the same no-oracle redirect.
    """
    if not state_cookie_matches(request, state):
        return None
    if not _consume_state(request.app, state, token):
        return None
    return port.consume_token(token)


def _magic_invalid_state_redirect() -> Response:
    """No-oracle 302 shared by every fail-closed verify path (issue #1004)."""
    return Response(status_code=302, headers={"location": "/login?reason=invalid_or_expired"})


@router.post("/auth/magic/start")
async def start_magic_link(
    request: Request, response: Response, payload: dict[str, object]
) -> dict:
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
    # Login CSRF fix (issue #1004): bind the token to a single-use
    # state that travels ONLY in the emailed link, so the verify URL
    # cannot be reconstructed from the token alone, and set the state
    # cookie in the initiating browser so the URL is not forwardable.
    state_ttl = _state_ttl_for(port)
    state = _issue_state(request.app, raw_token, ttl_seconds=state_ttl)
    set_state_cookie(response, state, max_age=state_ttl)
    verify_url = f"{base_url}/auth/magic/verify?token={raw_token}&state={state}"
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
    state: Annotated[str | None, Query()] = None,
) -> Response:
    """Consume the state, the token, set the session cookie, redirect home.

    First it validates the single-use ``state`` bound to this token
    at ``/auth/magic/start`` (issue #1004): missing / wrong / expired /
    replayed state returns the SAME no-oracle redirect as a bad token
    and does NOT consume the token — a user who clicks a truncated
    link can retry with the full URL. The state is spent first, then
    the token: both are one-shot, so nothing is left half-usable.

    It then resolves the ACTIVE user for the token's email via the
    :class:`AuthUsersPort` seam (issue #917); 302 to ``/`` with the
    ``apap_session`` cookie, or ``/unauthorized`` without one (fail
    closed). The route never tells the caller WHY it failed.
    """
    port: MagicLinkPort = request.app.state.magic_link_port
    secret: str = request.app.state.session_secret

    # Browser binding, single-use state, token — spent in that order
    # (issue #1004); every failure gets the same no-oracle redirect.
    email = _consume_bound_state(request, port, state, token)
    if email is None:
        return _magic_invalid_state_redirect()

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
    # The binding is spent: expire the state cookie so the browser
    # drops it together with the consumed server-side state.
    expire_state_cookie(redirect)
    # Mirror the OAuth callback's ``auth.login`` event (app.core.auth_flow)
    # so magic-link logins appear in the same audit stream. ``email`` is
    # redacted by ``log_safe``'s closed PII list.
    log_safe("auth.login", email=user.email, user_id=user.id)
    return redirect


__all__ = ["router"]
