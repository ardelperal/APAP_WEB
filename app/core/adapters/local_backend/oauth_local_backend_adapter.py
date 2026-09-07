"""LocalBackend adapter implementing :class:`OAuthPort` for the Google OAuth flow.

The adapter is the seam where the OAuth protocol meets the LocalBackend
HTTP transport. It wraps the three ``start_google_oauth`` /
``exchange_google_oauth_code`` / ``exchange_local_backend_oauth_code``
methods on :class:`app.core.local_backend.LocalPostgresExecutor` and projects
their transport-shaped return values to the :class:`OAuthUser` value
object the port declares.

The adapter is the ONLY place in the OAuth slice that imports
:class:`app.core.local_backend.LocalPostgresExecutor` (rule §31: domain depends
on Protocol, never on a concrete client). The application layer
imports the :class:`OAuthPort` Protocol and never sees this module.

PKCE generation lives here (not in the use case) because the
``code_verifier`` and ``code_challenge`` are part of the
protocol-level contract the port returns — the use case should
not be aware of which side of the exchange mints them. The
generator at :func:`app.core.pkce.generate_pkce_pair` is the
:class:`app.core.local_backend`-free helper the route layer used to
call inline (legacy ``app.core.auth_flow::start_google_login``);
moving the call into the adapter is the natural follow-up of the
hexagonal split.

Hexagonal taxonomy:

- Domain   :mod:`app.core.domain.oauth` — entities + Protocol errors.
- Port     :mod:`app.core.ports.oauth_port` — abstract surface.
- Application :mod:`app.core.application.oauth` — use cases.
- THIS    (this module) — LocalBackend impl.
- DI       :mod:`app.core.di.oauth_di` — wiring.
"""



from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.core.domain.oauth import PkcePair
from app.core.local_backend.oauth_google import (
    exchange_oauth_code,
    google_oauth_callback,
    start_google_oauth,
)
from app.core.pkce import generate_pkce_pair
from app.core.ports.oauth_port import OAuthUser


class LocalBackendOAuthAdapter:
    """LocalBackend implementation of :class:`OAuthPort`.

    The adapter is stateless and thread-safe. It holds a single
    :class:`LocalPostgresExecutor` reference passed at construction time;
    the DI layer (``app/core/di/oauth_di.py``) owns the client's
    lifecycle, not the adapter.
    """

    def __init__(self, client: SqlExecutor) -> None:
        """Store the LocalBackend client used for every OAuth round-trip.

        Args:
            client: The pooled :class:`LocalPostgresExecutor` from
                ``app.state.local_backend_client`` (production) or a
                test fake that subclasses ``LocalPostgresExecutor`` and
                overrides the three ``start_google_oauth`` /
                ``exchange_*`` methods.
        """
        self._client = client

    def start_google_login(self, redirect_uri: str) -> tuple[str, PkcePair]:
        """Mint a PKCE pair and return the Google authorization URL.

        The pair is generated here (not in the use case) so the
        application layer can stay transport-agnostic. The
        :class:`PkcePair` value object is what the port returns —
        the use case reads ``code_verifier`` from it to mint the
        ``apap_pkce`` cookie.

        The ``redirect_uri`` is forwarded verbatim to the LocalBackend
        client; the LocalBackend OAuth proxy adds it to the Google
        request as the ``redirect_uri`` query parameter.
        """
        code_verifier, code_challenge = generate_pkce_pair()
        result = start_google_oauth(redirect_uri, code_challenge)
        return str(result["authUrl"]), PkcePair(
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    def exchange_oauth_code(
        self,
        oauth_code: str,
        code_verifier: str,
    ) -> OAuthUser:
        """Exchange an LocalBackend-hosted ``local_backend_code`` for the user identity.

        Production path. The :class:`LocalPostgresExecutor` already raises
        :class:`app.core.data_access.BackendError` on a non-2xx
        response — the use case catches it (the §32.P4 narrowing).
        This adapter does not need to translate transport errors;
        they are already in the right Protocol-level shape.
        """
        result = exchange_oauth_code(
            {"oauth_code": oauth_code, "code_verifier": code_verifier}
        )
        user = result["user"]
        return OAuthUser(id=str(user["id"]), email=str(user["email"]))

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthUser:
        """Exchange a direct Google-issued ``code`` for the user identity.

        Legacy direct-callback path. Kept for tests that pre-date
        the LocalBackend OAuth proxy rollout. New flows should call
        :meth:`exchange_oauth_code` instead.
        """
        result = google_oauth_callback(
            {
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            }
        )
        user = result["user"]
        return OAuthUser(id=str(user["id"]), email=str(user["email"]))


__all__ = ["LocalBackendOAuthAdapter"]
