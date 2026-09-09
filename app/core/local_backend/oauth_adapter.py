"""LocalBackend adapter implementing :class:`OAuthPort` for the Google OAuth flow.

The adapter is the seam where the OAuth protocol meets the LocalBackend
HTTP endpoints (:mod:`app.core.local_backend.oauth_google`). It wraps the
three ``start_google_oauth`` / ``exchange_insforge_oauth_code`` /
``exchange_google_oauth_code`` FastAPI endpoint calls and projects their
response dicts to the :class:`OAuthUser` value object and
:class:`PkcePair` the port declares.

The adapter is stateless and thread-safe. It holds a single
:class:`httpx.Client` lazily created on first use and reused for the
application lifetime. The DI layer (``app/core/di/oauth_di.py``) owns
the adapter's lifecycle.
"""

from __future__ import annotations

import httpx

from app.core.data_access import InsForgeError
from app.core.domain.oauth import PkcePair
from app.core.pkce import generate_pkce_pair
from app.core.ports.oauth_port import OAuthUser


class LocalBackendOAuthAdapter:
    """LocalBackend implementation of :class:`OAuthPort`.

    The adapter is stateless and thread-safe. It lazily creates one
    :class:`httpx.Client` on first HTTP call and reuses it for all
    subsequent calls. The DI layer owns the adapter lifecycle.
    """

    def __init__(self, base_url: str) -> None:
        """Store the base URL for OAuth endpoint calls.

        Args:
            base_url: The scheme+host of the running application
                (e.g. ``"http://localhost:8000"``). Used as the
                ``base_url`` for the internal :class:`httpx.Client`.
        """
        self._base_url = base_url.rstrip("/")
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Lazily create and cache the shared httpx client."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=10.0,
                follow_redirects=True,
            )
        return self._client

    def start_google_login(self, redirect_uri: str) -> tuple[str, PkcePair]:
        """Mint a PKCE pair and return the Google authorization URL.

        Calls ``GET /auth/oauth/google``.
        """
        code_verifier, code_challenge = generate_pkce_pair()
        resp = self._get_client().get(
            "/auth/oauth/google",
            params={"redirect_uri": redirect_uri, "code_challenge": code_challenge},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InsForgeError(
                message="oauth_start_failed",
                detail=f"Google OAuth start failed: {exc.response.status_code}",
            ) from exc
        data = resp.json()
        return data["authUrl"], PkcePair(
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthUser:
        """Exchange an InsForge-hosted ``insforge_code`` for the user identity.

        Calls ``POST /auth/oauth/exchange``.
        """
        resp = self._get_client().post(
            "/auth/oauth/exchange",
            json={"code": insforge_code, "code_verifier": code_verifier},
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InsForgeError(
                message="oauth_exchange_failed",
                detail=f"InsForge OAuth exchange failed: {exc.response.status_code}",
            ) from exc
        data = resp.json()
        return OAuthUser(
            id=data["user"]["id"],
            email=data["user"]["email"],
        )

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthUser:
        """Exchange a direct Google-issued ``code`` for the user identity.

        Calls ``POST /auth/oauth/google/callback``.
        """
        resp = self._get_client().post(
            "/auth/oauth/google/callback",
            json={
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InsForgeError(
                message="oauth_direct_exchange_failed",
                detail=f"Google direct OAuth exchange failed: {exc.response.status_code}",
            ) from exc
        data = resp.json()
        # Legacy endpoint returns {"token": "...", "user": {...}}
        user_data = data.get("user", {})
        return OAuthUser(
            id=user_data.get("id", "unknown"),
            email=user_data.get("email", ""),
        )

    def close(self) -> None:
        """Close the internal httpx client if it was created."""
        if self._client is not None:
            self._client.close()
            self._client = None
