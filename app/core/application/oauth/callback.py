"""Use case: handle the OAuth callback.

The callback use case is the heart of the OAuth flow. It:

1. Decides which exchange method to call (the modern
   InsForge-hosted path with ``insforge_code``, or the legacy
   direct-Google path with ``code``).
2. Calls the right :class:`OAuthPort` method with the PKCE
   verifier (carried in the short-lived ``apap_pkce`` cookie;
   the route layer is responsible for cookie parsing).
3. Looks the returned email up in ``usuarios_autorizados`` via
   the :class:`AuthUsersPort` to resolve the user's role and
   active status.
4. Returns an :class:`AuthenticatedSession` ready to be signed
   into the ``apap_session`` cookie by the route layer.

The use case raises the Protocol-level errors defined in
:mod:`app.core.domain.oauth.errors` for the three failure
modes the route layer must distinguish (rule §32.P4 — the
legacy code caught a bare ``InsForgeError`` and turned every
failure into a ``/login`` redirect):

- :class:`CallbackInvalidError` — neither code was supplied.
  The route layer redirects to ``/login``.
- :class:`UserNotAuthorizedError` — the email did not resolve
  to an active row. The route layer redirects to
  ``/unauthorized`` AND clears the ``apap_pkce`` cookie so the
  browser does not replay the bad verifier.
- :class:`app.core.data_access.InsForgeError` — the transport
  exchange failed (expired code, wrong verifier, network
  error, ...). The route layer catches and redirects to
  ``/login`` (the same shape the legacy code had, but now
  narrowed to the single call site that can actually raise it).

Hexagonal contract:

- Inputs: the :class:`OAuthPort` + :class:`AuthUsersPort` (both
  Protocol abstractions; rule §31) and the raw callback
  parameters (``insforge_code``, ``code``, ``code_verifier``,
  ``redirect_uri``).
- Outputs: an :class:`AuthenticatedSession`.
- Side effects: a transport round-trip per exchange method, and
  one database read for the user lookup.
"""


from __future__ import annotations

from app.core.data_access import InsForgeError
from app.core.domain.auth.user import AuthorizedUser
from app.core.domain.oauth import (
    AuthenticatedSession,
    CallbackInvalidError,
    UserNotAuthorizedError,
)
from app.core.ports.auth_port import AuthUsersPort
from app.core.ports.oauth_port import OAuthPort


def callback(
    oauth_port: OAuthPort,
    auth_port: AuthUsersPort,
    *,
    insforge_code: str | None,
    code: str | None,
    code_verifier: str,
    redirect_uri: str,
) -> AuthenticatedSession:
    """Exchange the OAuth code and resolve the user identity.

    The use case is a thin orchestrator over the two ports. All
    "what does it mean?" decisions (which code to prefer, what
    counts as not authorized) live here; the transport details
    (cookie parsing, response building, session signing) live in
    the route layer.

    Args:
        oauth_port: The :class:`OAuthPort` injected by the DI
            layer (``app/core/di/oauth_di.py``).
        auth_port: The :class:`AuthUsersPort` injected by the DI
            layer (``app/core/di/auth_di.py``).
        insforge_code: The temporary code in the callback URL when
            InsForge's hosted proxy is the front. ``None`` when the
            request is on the legacy direct-callback path.
        code: The Google-issued authorization code on the legacy
            direct-callback path. ``None`` when the request is on
            the InsForge-hosted path.
        code_verifier: The PKCE verifier recovered from the
            ``apap_pkce`` cookie. The route layer is responsible
            for cookie parsing; this use case receives the raw
            string.
        redirect_uri: The application's callback URL. The legacy
            direct-callback path needs it to match the one sent
            at start time; the InsForge-hosted path does not.

    Returns:
        The :class:`AuthenticatedSession` ready to be signed into
        the ``apap_session`` cookie.

    Raises:
        CallbackInvalidError: When neither ``insforge_code`` nor
            ``code`` was supplied. The route layer redirects to
            ``/login``.
        UserNotAuthorizedError: When the email returned by the
            exchange does not resolve to an active row in
            ``usuarios_autorizados``. The route layer redirects
            to ``/unauthorized`` and clears the ``apap_pkce``
            cookie.
        InsForgeError: When the transport exchange fails. The
            route layer catches and redirects to ``/login``. This
            is the §32.P4 narrowing of the legacy
            ``except InsForgeError`` bucket — the catch is now
            scoped to the single exchange call site, not the
            whole route.
    """
    if insforge_code:
        oauth_user = oauth_port.exchange_insforge_oauth_code(
            insforge_code=insforge_code,
            code_verifier=code_verifier,
        )
    elif code:
        oauth_user = oauth_port.exchange_google_oauth_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
    else:
        raise CallbackInvalidError()

    user: AuthorizedUser | None = auth_port.get_user_by_email(oauth_user.email)
    if user is None:
        raise UserNotAuthorizedError(oauth_user.email)

    return AuthenticatedSession.from_authorized_user(user)


__all__ = ["callback"]
