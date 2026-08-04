"""Use case: start the Google OAuth login flow.

The use case returns the (PKCE pair, auth URL) tuple the route
layer needs to (a) mint the short-lived ``apap_pkce`` cookie and
(b) redirect the user to Google. The PKCE pair is minted inside
the adapter so the application layer can stay transport-agnostic;
this use case is the orchestrator that hands the pair + URL to
the route.

Hexagonal contract:

- Inputs: the :class:`OAuthPort` (depends on the Protocol, not on
  any concrete backend) and the configured :class:`Settings`
  (for the ``google_redirect_uri``).
- Outputs: a ``(pkce_pair, auth_url)`` tuple the route consumes.
- Side effects: none (the adapter calls the backend, but the use
  case is a pure delegator).

The configuration check (is Google OAuth set up?) is the same
one :func:`app.core.application.oauth.login_page.login_page` uses.
The use case raises :class:`OAuthNotConfiguredError` when the
configuration is missing; the route layer translates that to the
same 503 JSON the legacy code produced. The duplicate check
between this use case and :func:`login_page` is intentional: the
two use cases are independent entry points (the user can hit
``/login`` directly OR click the Gmail button which navigates
to ``/auth/google``), so each must defend on its own.
"""


from __future__ import annotations

from app.core.config import Settings
from app.core.domain.oauth import OAuthNotConfiguredError, PkcePair
from app.core.ports.oauth_port import OAuthPort


def start_google_login(
    port: OAuthPort,
    settings: Settings,
) -> tuple[PkcePair, str]:
    """Start the Google OAuth flow and return the (pair, auth_url) for the route.

    The configuration check (empty ``google_client_id`` or
    ``google_client_secret``) raises
    :class:`OAuthNotConfiguredError` so the route layer can map
    the failure to a single ``503`` response. The actual API call
    is delegated to :meth:`OAuthPort.start_google_login` — this
    use case only applies the precondition and hands the result
    back.

    Returns:
        A ``(pkce_pair, auth_url)`` tuple. The route layer stores
        ``pkce_pair.code_verifier`` in the ``apap_pkce`` cookie
        (signed with ``settings.session_secret``) and redirects to
        ``auth_url``.

    Raises:
        OAuthNotConfiguredError: When the Google OAuth env vars are
            not set. The route layer catches and translates to
            ``503``.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise OAuthNotConfiguredError()
    auth_url, pkce_pair = port.start_google_login(settings.google_redirect_uri)
    return pkce_pair, auth_url


__all__ = ["start_google_login"]
