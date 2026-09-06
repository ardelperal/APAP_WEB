"""InsForge adapter implementing :class:`OAuthPort` for the Google OAuth flow.

The adapter is the seam where the OAuth protocol meets the InsForge
HTTP transport. It wraps the three ``start_google_oauth`` /
``exchange_google_oauth_code`` / ``exchange_insforge_oauth_code``
methods on :class:`app.core.insforge.InsForgeClient` and projects
their transport-shaped return values to the :class:`OAuthUser` value
object the port declares.

The adapter is the ONLY place in the OAuth slice that imports
:class:`app.core.insforge.InsForgeClient` (rule §31: domain depends
on Protocol, never on a concrete client). The application layer
imports the :class:`OAuthPort` Protocol and never sees this module.

PKCE generation lives here (not in the use case) because the
``code_verifier`` and ``code_challenge`` are part of the
protocol-level contract the port returns — the use case should
not be aware of which side of the exchange mints them. The
generator at :func:`app.core.pkce.generate_pkce_pair` is the
:class:`app.core.insforge`-free helper the route layer used to
call inline (legacy ``app.core.auth_flow::start_google_login``);
moving the call into the adapter is the natural follow-up of the
hexagonal split.

Hexagonal taxonomy:

- Domain   :mod:`app.core.domain.oauth` — entities + Protocol errors.
- Port     :mod:`app.core.ports.oauth_port` — abstract surface.
- Application :mod:`app.core.application.oauth` — use cases.
- THIS    (this module) — InsForge impl.
- DI       :mod:`app.core.di.oauth_di` — wiring.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).



from __future__ import annotations

from app.core.domain.oauth import PkcePair
from app.core.insforge import InsForgeClient
from app.core.pkce import generate_pkce_pair
from app.core.ports.oauth_port import OAuthUser


class InsForgeOAuthAdapter:
    """InsForge implementation of :class:`OAuthPort`.

    The adapter is stateless and thread-safe. It holds a single
    :class:`InsForgeClient` reference passed at construction time;
    the DI layer (``app/core/di/oauth_di.py``) owns the client's
    lifecycle, not the adapter.
    """

    def __init__(self, client: InsForgeClient) -> None:
        """Store the InsForge client used for every OAuth round-trip.

        Args:
            client: The pooled :class:`InsForgeClient` from
                ``app.state.insforge_client`` (production) or a
                test fake that subclasses ``InsForgeClient`` and
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

        The ``redirect_uri`` is forwarded verbatim to the InsForge
        client; the InsForge OAuth proxy adds it to the Google
        request as the ``redirect_uri`` query parameter.
        """
        code_verifier, code_challenge = generate_pkce_pair()
        auth_url = self._client.start_google_oauth(redirect_uri, code_challenge)
        return auth_url, PkcePair(
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthUser:
        """Exchange an InsForge-hosted ``insforge_code`` for the user identity.

        Production path. The :class:`InsForgeClient` already raises
        :class:`app.core.data_access.InsForgeError` on a non-2xx
        response — the use case catches it (the §32.P4 narrowing).
        This adapter does not need to translate transport errors;
        they are already in the right Protocol-level shape.
        """
        result = self._client.exchange_insforge_oauth_code(
            insforge_code=insforge_code,
            code_verifier=code_verifier,
        )
        return OAuthUser(id=result.user.id, email=result.user.email)

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthUser:
        """Exchange a direct Google-issued ``code`` for the user identity.

        Legacy direct-callback path. Kept for tests that pre-date
        the InsForge OAuth proxy rollout. New flows should call
        :meth:`exchange_insforge_oauth_code` instead.
        """
        result = self._client.exchange_google_oauth_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        return OAuthUser(id=result.user.id, email=result.user.email)


__all__ = ["InsForgeOAuthAdapter"]
