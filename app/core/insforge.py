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
import re
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

        The InsForge endpoint returns a JSON envelope of the shape
        ``{"rows": [...], "rowCount": N, "fields": [...]}``. This method
        unpacks the ``rows`` list so call sites can do the natural
        thing (``rows[0] if rows else None``) and not have to know
        about the envelope. Regression caught in production on
        2026-06-28 — the function was returning the full envelope
        and every ``rows[0]`` call site crashed with
        ``KeyError: 0``.
        """
        response = self._client.post(
            "/api/database/advance/rawsql",
            json={"query": query, "params": params or []},
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        body = _safe_json(response)
        # Accept both the real InsForge envelope and a bare list
        # (the in-process tests bypass HTTP and return the list
        # directly).
        if isinstance(body, dict) and "rows" in body:
            return body["rows"]
        if isinstance(body, list):
            return body
        raise InsForgeError(
            response.status_code,
            body,
        )

    # --- Storage buckets ------------------------------------------------

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
        """Return bucket metadata from the storage admin surface.

        Uses the documented bucket-list endpoint instead of upload or
        download APIs. A bucket whose visibility is not reported is still
        returned with ``isPublic=None`` so callers can fail closed.
        """
        safe_bucket = _validate_bucket_name(bucket_name)
        response = self._client.get("/api/storage/buckets")
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        body = _safe_json(response)
        for item in _extract_bucket_items(body):
            name = _bucket_name_from_item(item)
            if name == safe_bucket:
                return {
                    "bucketName": safe_bucket,
                    "isPublic": _bucket_visibility_from_item(item),
                }
        return None

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]:
        """Ensure a storage bucket exists and fail closed unless it is private.

        APAP migration bootstrap only supports private buckets. Passing
        ``is_public=True`` is rejected before any HTTP call so a caller
        cannot accidentally create a public photo bucket.
        """
        safe_bucket = _validate_bucket_name(bucket_name)
        if is_public:
            raise ValueError("APAP migration buckets must be private (is_public=False)")

        existing = self.get_bucket(safe_bucket)
        if existing is not None:
            _require_private_bucket(safe_bucket, existing)
            return existing

        response = self._client.post(
            "/api/storage/buckets",
            json={"bucketName": safe_bucket, "isPublic": False},
        )
        if response.status_code != 409 and not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))

        bucket = self.get_bucket(safe_bucket)
        if bucket is None:
            raise InsForgeError(
                500,
                {
                    "error": "bucket_readback_missing",
                    "message": f"Bucket {safe_bucket!r} was not visible after create",
                },
            )
        _require_private_bucket(safe_bucket, bucket)
        return bucket

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


_SAFE_BUCKET_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_bucket_name(bucket_name: str) -> str:
    """Return a safe bucket name or raise before any HTTP call."""
    if not _SAFE_BUCKET_NAME.match(bucket_name):
        raise ValueError(
            f"unsafe bucket name {bucket_name!r}; must match {_SAFE_BUCKET_NAME.pattern}"
        )
    return bucket_name


def _extract_bucket_items(body: Any) -> list[Any]:
    """Normalize InsForge bucket list response shapes."""
    if isinstance(body, dict):
        buckets = body.get("buckets", body.get("data", []))
    else:
        buckets = body
    if isinstance(buckets, dict):
        return list(buckets.values())
    if isinstance(buckets, list):
        return buckets
    return []


def _bucket_name_from_item(item: Any) -> str | None:
    """Extract the bucket name from documented and MCP-shaped items."""
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in ("bucketName", "name", "bucket", "id"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


def _bucket_visibility_from_item(item: Any) -> bool | None:
    """Extract bucket visibility, or ``None`` when the API omits it."""
    if not isinstance(item, dict):
        return None
    for key in ("isPublic", "is_public", "public"):
        value = item.get(key)
        if isinstance(value, bool):
            return value
    return None


def _require_private_bucket(bucket_name: str, bucket: dict[str, Any]) -> None:
    """Fail closed unless bucket read-back proves ``isPublic`` is False."""
    visibility = bucket.get("isPublic")
    if visibility is False:
        return
    if visibility is True:
        raise InsForgeError(
            409,
            {
                "error": "bucket_public_violation",
                "message": f"Bucket {bucket_name!r} exists but is public; recreate it private",
            },
        )
    raise InsForgeError(
        502,
        {
            "error": "bucket_visibility_unknown",
            "message": f"Bucket {bucket_name!r} visibility could not be verified",
        },
    )


def _safe_json(response: httpx.Response) -> Any:
    """Parse JSON or return raw text if the body is not JSON."""
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return response.text
