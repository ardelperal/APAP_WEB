"""InsForge REST client.

Thin async HTTPX wrapper around the public InsForge REST API. Used by:

- the bootstrap seed to create the ``authorized_users`` table and the
  first developer user (privileged operations, requires the service key);
- the Google OAuth flow (``/api/auth/oauth/google`` + callback);
- the allowlist middleware to look up an email in ``authorized_users``.

All HTTP errors are surfaced as :class:`InsForgeError` so the caller can
decide whether to log, retry, or fall back. The transport is injectable
so tests can use ``httpx.MockTransport`` without hitting the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class OAuthExchangeResult:
    """Result of exchanging a Google OAuth ``code`` for an InsForge JWT."""

    token: str
    user: InsForgeUser


@dataclass(frozen=True, slots=True)
class InsForgeUser:
    """The user payload returned by InsForge after a successful exchange."""

    id: str
    email: str


class InsForgeError(RuntimeError):
    """Raised when the InsForge API returns a non-2xx response."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"InsForge {status_code}: {body!r}")


class InsForgeClient:
    """Synchronous HTTPX client for the InsForge REST API.

    Designed for the small surface area APAP_WEB needs: privileged SQL
    for setup/seed, the Google OAuth flow, and allowlist lookups. The
    service key is used as the bearer token for privileged operations;
    the exchange endpoint returns a JWT that the app stores as the
    session cookie.
    """

    def __init__(
        self,
        base_url: str,
        service_key: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        # Strip trailing slash so URL joining is predictable.
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {service_key}"},
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> InsForgeClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- Database ------------------------------------------------------

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute raw SQL via ``/api/database/advance/rawsql``.

        Returns the list of result rows (empty for non-SELECT queries).
        INSERT/UPDATE/DELETE with ``RETURNING`` also return rows.
        """
        response = self._client.post(
            "/api/database/advance/rawsql",
            json={"query": query, "params": params or []},
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        return _safe_json(response)

    # --- Google OAuth --------------------------------------------------

    def start_google_oauth(
        self,
        redirect_uri: str,
        code_challenge: str,
    ) -> str:
        """Start the Google OAuth flow and return the authorization URL.

        The caller should ``RedirectResponse`` the user to this URL.
        The redirect includes the PKCE ``code_challenge`` (the SHA-256
        of a random ``code_verifier`` generated server-side and held
        in the session until the callback).
        """
        response = self._client.get(
            "/api/auth/oauth/google",
            params={"redirect_uri": redirect_uri, "code_challenge": code_challenge},
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        body = _safe_json(response)
        if not isinstance(body, dict) or "authUrl" not in body:
            raise InsForgeError(response.status_code, body)
        return body["authUrl"]

    def exchange_google_oauth_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> OAuthExchangeResult:
        """Exchange a Google OAuth ``code`` for an InsForge JWT and user.

        Legacy direct-callback path (kept for tests that pre-date the
        InsForge OAuth proxy rollout). New flows should call
        ``exchange_insforge_oauth_code`` instead — InsForge now fronts
        Google with its own hosted OAuth proxy and sends an
        ``insforge_code`` to the app, not the raw Google ``code``.
        """
        response = self._client.post(
            "/api/auth/oauth/google/callback",
            json={
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        body = _safe_json(response)
        if not isinstance(body, dict) or "token" not in body or "user" not in body:
            raise InsForgeError(response.status_code, body)
        user_payload = body["user"]
        if not isinstance(user_payload, dict) or "email" not in user_payload:
            raise InsForgeError(response.status_code, body)
        return OAuthExchangeResult(
            token=body["token"],
            user=InsForgeUser(id=str(user_payload["id"]), email=str(user_payload["email"])),
        )

    def exchange_insforge_oauth_code(
        self,
        insforge_code: str,
        code_verifier: str,
    ) -> OAuthExchangeResult:
        """Exchange an InsForge-hosted ``insforge_code`` for an InsForge JWT + user.

        InsForge's hosted OAuth proxy (api.insforge.dev/auth/v1/shared/callback)
        fronts the underlying Google/Discord/etc. flow and, once the user
        consents, redirects the browser to the app's callback URL with
        ``?insforge_code=<temporary>``. The app then exchanges that code
        here with the PKCE verifier minted at ``/login`` time.

        Endpoint contract (per InsForge auth SDK docs):
            POST /api/auth/oauth/exchange?client_type=web
            body: {"code": insforge_code, "code_verifier": code_verifier}
            200:  {"user": {"id", "email", ...}, "accessToken", "csrfToken"}
            401:  INVALID_CREDENTIALS (the insforge_code expired or is wrong)
        """
        response = self._client.post(
            "/api/auth/oauth/exchange",
            params={"client_type": "web"},
            json={
                "code": insforge_code,
                "code_verifier": code_verifier,
            },
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        body = _safe_json(response)
        if not isinstance(body, dict) or "user" not in body:
            raise InsForgeError(response.status_code, body)
        user_payload = body["user"]
        if not isinstance(user_payload, dict) or "email" not in user_payload:
            raise InsForgeError(response.status_code, body)
        # ``accessToken`` is the bearer JWT; ``refreshToken`` is null
        # for web clients (InsForge stores it in an httpOnly cookie).
        token = str(body.get("accessToken", "") or "")
        if not token:
            raise InsForgeError(response.status_code, body)
        return OAuthExchangeResult(
            token=token,
            user=InsForgeUser(
                id=str(user_payload["id"]),
                email=str(user_payload["email"]),
            ),
        )


def _safe_json(response: httpx.Response) -> Any:
    """Parse JSON or return raw text if the body is not JSON."""
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return response.text
