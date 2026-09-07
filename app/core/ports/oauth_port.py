"""Hexagonal port for the OAuth login flow surface.

The application layer depends on this :class:`Protocol`; the
InsForge adapter implements it. Tests can implement it with an
in-memory fake without spinning up transport, InsForge, or HTTP.

The port carries three operations, one per OAuth-flow concern:

1. :meth:`OAuthPort.start_google_login` — generate a PKCE pair and
   ask the backend (InsForge) for the Google authorization URL.
2. :meth:`OAuthPort.exchange_insforge_oauth_code` — exchange an
   InsForge-hosted ``insforge_code`` (the post-InsForge-OAuth-proxy
   flow) for an :class:`OAuthUser` (the user identity returned by
   InsForge). This is the production path: InsForge fronts Google
   and forwards the user back to the app with a temporary
   ``insforge_code`` query parameter.
3. :meth:`OAuthPort.exchange_google_oauth_code` — exchange a direct
   Google-issued ``code`` (the pre-InsForge-OAuth-proxy flow) for an
   :class:`OAuthUser`. Kept so existing test suites that pre-date
   the InsForge OAuth-proxy rollout keep working.

The :class:`OAuthUser` value object is the shape the port returns
for the two exchange methods. It is intentionally minimal: just
``id`` and ``email`` (the only fields the InsForge REST contract
returns in the post-exchange ``user`` payload). The application
layer then looks the email up in ``usuarios_autorizados`` via the
:class:`~app.core.ports.auth_port.AuthUsersPort` to resolve the
domain :class:`~app.core.domain.auth.rol.Rol` and the
``activo`` flag — keeping the two ports independent and the OAuth
port free of SQL/table knowledge.

The port does NOT catch transport errors: the adapter re-raises
:class:`~app.core.data_access.BackendError` and the use case
catches it. This is the §32.P4 fix: the legacy
``app.core.auth_flow.callback`` caught a bare ``BackendError``
and silently turned every transport failure into a
``/redirect(/login)``. The new use case catches the SAME
:class:`BackendError` type, but only on the exchange call site —
so the redaction list still works, but the catch is no longer a
catch-all for every "this didn't work" outcome.

Hexagonal taxonomy:

- Domain   :mod:`app.core.domain.oauth` — entities + Protocol errors.
- Port     (this module) — abstract surface.
- Application :mod:`app.core.application.oauth` — use cases.
- Adapter  :mod:`app.core.adapters.insforge.oauth_insforge_adapter` — InsForge impl.
- DI       :mod:`app.core.di.oauth_di` — wiring.

Rule §31 (domain services depend on Protocol abstractions): every
method here takes no concrete backend client; the adapter chooses its
own transport.
Rule §22 (SQL/service separation): no SQL lives here; the
:class:`app.core.insforge.LocalPostgresExecutor` calls the HTTP endpoints
the adapter wraps.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.domain.oauth import PkcePair


@dataclass(frozen=True, slots=True)
class OAuthUser:
    """The user identity returned by the backend after a code exchange.

    Mirrors the documented InsForge exchange response
    ``{"user": {"id": ..., "email": ...}, "accessToken": ...}``. Only
    the two fields the OAuth flow actually needs are surfaced; the
    full ``accessToken`` (the bearer JWT the app stores in the
    session cookie) is consumed by the adapter and not returned to
    the application layer, because the application layer does not
    need it — the signed session cookie is what the middleware
    re-validates on every request.

    Attributes:
        id: The InsForge user id (a UUID-shaped string). The
            application layer uses this as a non-PII identifier in
            ``log_safe`` events.
        email: The user's email at exchange time. The application
            layer normalizes it before looking it up in
            ``usuarios_autorizados``.
    """

    id: str
    email: str


class OAuthPort(Protocol):
    """Abstract surface for the OAuth login flow.

    Implementations:

    - :class:`app.core.adapters.insforge.oauth_insforge_adapter.InsForgeOAuthAdapter`
      — production adapter, talks to InsForge via
      :class:`app.core.insforge.LocalPostgresExecutor`.
    - Test fakes (in ``tests/``) — in-memory adapters that record
      calls or raise on demand without any transport.
    """

    def start_google_login(self, redirect_uri: str) -> tuple[str, PkcePair]:
        """Mint a PKCE pair and return the Google authorization URL.

        The implementation generates a fresh (verifier, challenge)
        pair, asks the backend for the Google auth URL, and returns
        BOTH. The route layer signs the verifier into the
        short-lived ``apap_pkce`` cookie; the challenge is what the
        backend includes in the Google auth request.

        Args:
            redirect_uri: The application's callback URL the
                authorization server will redirect to after consent.
                Same value the use case sends to both exchange
                methods.

        Returns:
            A ``(auth_url, pkce_pair)`` tuple. ``auth_url`` is the
            fully-formed Google authorization URL the route redirects
            the user to. ``pkce_pair`` is the typed value object
            the route reads ``code_verifier`` from to mint the
            cookie.
        """
        ...

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthUser:
        """Exchange an InsForge-hosted ``insforge_code`` for the user identity.

        This is the production post-InsForge-OAuth-proxy path:
        InsForge's hosted proxy fronts Google (and other providers)
        with its own OAuth flow, then redirects the user back to the
        app with ``?insforge_code=<temporary>``. The app exchanges
        that code here with the PKCE verifier minted at
        ``/login`` time.

        Args:
            insforge_code: The temporary code in the callback URL.
            code_verifier: The PKCE verifier from the ``apap_pkce``
                cookie.

        Returns:
            The :class:`OAuthUser` resolved by InsForge.

        Raises:
            app.core.data_access.BackendError: When the backend
                returns a non-2xx response (expired code, wrong
                verifier, etc.). The use case catches and re-raises
                as a redirect to ``/login`` (the §32.P4 fix narrows
                the catch to the single exchange call site).
        """
        ...

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthUser:
        """Exchange a direct Google-issued ``code`` for the user identity.

        Legacy direct-callback path (kept for tests that pre-date
        the InsForge OAuth proxy rollout). New flows should call
        :meth:`exchange_insforge_oauth_code` instead.

        Args:
            code: The Google-issued authorization code.
            code_verifier: The PKCE verifier from the ``apap_pkce``
                cookie.
            redirect_uri: The application's callback URL (must
                match the one used in the start step).

        Returns:
            The :class:`OAuthUser` resolved by InsForge.

        Raises:
            app.core.data_access.BackendError: When the backend
                returns a non-2xx response. Same handling as
                :meth:`exchange_insforge_oauth_code`.
        """
        ...


__all__ = ["OAuthPort", "OAuthUser"]
