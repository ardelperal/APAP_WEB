"""InsForge REST client.

Thin async HTTPX wrapper around the public InsForge REST API. Used by:

- the bootstrap seed to create the ``authorized_users`` table and the
  first developer user (privileged operations, requires the service key);
- the Google OAuth flow (``/api/auth/oauth/google`` + callback);
- the allowlist middleware to look up an email in ``authorized_users``.

HTTP errors are surfaced as :class:`InsForgeError` so the caller can
decide whether to log, retry, or fall back. The :meth:`InsForgeClient.execute_sql`
method additionally translates the most common transport-layer error
(Postgres ``23505`` unique-violation reported as HTTP 409) into the
Protocol-level :class:`~app.core.data_access.DuplicateKeyError` so
domain code can ``except DuplicateKeyError`` without inspecting the
envelope. The translation lives in
:mod:`app.core.insforge_error_translation` to keep this module under the
700-line budget (AGENTS.md rule 21). The transport is injectable so
tests can use ``httpx.MockTransport`` without hitting the network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.data_access import InsForgeError
from app.core.insforge_error_translation import translate_post_error


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


# ``InsForgeError`` is re-exported from ``app.core.data_access`` so the
# Protocol-level ``DuplicateKeyError`` can inherit from it cleanly
# (without a circular import between this module and ``data_access``).
# Existing ``from app.core.insforge import InsForgeError`` imports keep
# working through this re-export.


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

        409 responses carrying a Postgres ``23505`` SQLSTATE (or a
        message containing ``"duplicate"`` / ``"unique"``) are
        translated to :class:`~app.core.data_access.UniqueViolationError`
        so domain code can ``except DuplicateKeyError`` without
        inspecting the transport envelope. Every other non-2xx
        response continues to surface as :class:`InsForgeError` —
        the global handler in :mod:`app.core.insforge_error_handler`
        still owns the 502 conversion for those.
        """
        try:
            body = self._post_raw_sql(query, params)
        except InsForgeError as exc:
            # Translate the transport error to a Protocol-level error when
            # possible; the ``from exc`` clause keeps the original
            # ``InsForgeError`` as ``__cause__`` for postmortem tracebacks.
            raise translate_post_error(exc) from exc
        # Accept both the real InsForge envelope and a bare list
        # (the in-process tests bypass HTTP and return the list
        # directly).
        if isinstance(body, dict) and "rows" in body:
            return body["rows"]
        if isinstance(body, list):
            return body
        raise InsForgeError(500, body)

    def _post_raw_sql(
        self,
        query: str,
        params: list[Any] | None,
    ) -> Any:
        """POST a raw SQL statement and return the parsed body, translating transport errors.

        Extracted from :meth:`execute_sql` so the ``try/except InsForgeError``
        pattern does not nest an abstract ``raise`` inside the body of
        ``execute_sql`` (ruff TRY301). The translator (``translate_post_error``)
        converts 409 uniqueness bodies to :class:`DuplicateKeyError` /
        :class:`UniqueViolationError`; every other non-2xx response surfaces as
        the original :class:`InsForgeError` so the global handler still owns
        the 502 conversion for transport failures.
        """
        response = self._client.post(
            "/api/database/advance/rawsql",
            json={"query": query, "params": params or []},
        )
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))
        return _safe_json(response)

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

    # --- Storage objects -----------------------------------------------

    def upload_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
    ) -> dict[str, Any]:
        """Upload bytes to ``bucket`` under ``key`` via the three-step S3-compatible flow.

        The contract (pinned in
        ``docs/discovery/storage-contract-2026-Q3.md`` by operator sentinel
        evidence) is:

        1. ``POST /api/storage/buckets/{bucket}/upload-strategy`` with body
           ``{filename, contentType, size}`` → strategy response carrying
           ``{method, uploadUrl, fields, key, confirmRequired, confirmUrl,
           expiresAt}``.
        2. **Transfer**: when the strategy returned ``fields``, the body is
           sent as ``multipart/form-data`` to ``uploadUrl`` via POST (S3
           variant); when ``fields`` is absent, the body is sent as raw
           bytes via PUT (Local variant).
        3. **Confirm**: when ``confirmRequired=True``, the upload is
           finalised with a POST to ``confirmUrl``.

        The bucket name is validated against ``_SAFE_BUCKET_NAME`` BEFORE
        any HTTP call. ``upload_object`` raises ``ValueError`` for an
        unsafe bucket name and ``InsForgeError`` for any non-2xx step.

        The client proposes ``filename=key`` (caller may pre-derive the key
        as ``<sha256>.<ext>``); the server may rename on collision and
        returns the canonical key in the strategy response, which is then
        re-surfaced via the confirm response. The caller reads the
        canonical key from the returned dict.

        PR4b 4R WARN-4: the three steps are extracted into named helpers
        (``_request_upload_strategy``, ``_transfer_upload``, and
        ``_confirm_upload``) so the orchestration in ``upload_object``
        reads top-to-bottom as "validate → strategy → transfer → confirm".
        The behaviour is unchanged; the 28 ``test_insforge_storage_methods``
        atoms pin the wire contract.
        """
        safe_bucket = _validate_bucket_name(bucket)
        size = len(body)

        # Step 1 — request upload strategy.
        strategy_body = self._request_upload_strategy(
            safe_bucket, key=key, content_type=content_type, size=size
        )

        # Step 2 — transfer the bytes (POST when fields present, PUT when absent).
        self._transfer_upload(
            strategy_body=strategy_body,
            key=key,
            body=body,
            content_type=content_type,
        )

        # Step 3 — confirm when required; otherwise echo the strategy's canonical key.
        confirm_required = bool(strategy_body.get("confirmRequired", False))
        if confirm_required:
            confirm_body = self._confirm_upload(strategy_body=strategy_body)
            if isinstance(confirm_body, dict):
                return confirm_body
            return {"key": key}

        # No confirm required — echo the strategy's canonical key.
        canonical_key = (
            strategy_body.get("key")
            if isinstance(strategy_body.get("key"), str)
            else key
        )
        return {"key": canonical_key}

    def _request_upload_strategy(
        self,
        safe_bucket: str,
        *,
        key: str,
        content_type: str,
        size: int,
    ) -> dict[str, Any]:
        """Step 1 — request the upload strategy from InsForge.

        Returns the parsed strategy body (a ``dict``). Raises
        ``InsForgeError`` on a non-2xx response, on a non-dict body, or
        on a body missing the required ``uploadUrl`` field. The bucket
        name has already been validated by ``_validate_bucket_name``.
        """
        safe_key = _validate_storage_key(key)
        strategy = self._client.post(
            f"/api/storage/buckets/{safe_bucket}/upload-strategy",
            json={
                "filename": safe_key,
                "contentType": content_type,
                "size": size,
            },
        )
        if not strategy.is_success:
            raise InsForgeError(strategy.status_code, _safe_json(strategy))
        strategy_body = _safe_json(strategy)
        if not isinstance(strategy_body, dict):
            raise InsForgeError(strategy.status_code, strategy_body)
        upload_url = strategy_body.get("uploadUrl")
        if not isinstance(upload_url, str) or not upload_url:
            raise InsForgeError(
                strategy.status_code,
                {"error": "upload_strategy_missing_url", "received": strategy_body},
            )
        return strategy_body

    def _transfer_upload(
        self,
        *,
        strategy_body: dict[str, Any],
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        """Step 2 — transfer the bytes to the strategy's ``uploadUrl``.

        When the strategy returned ``fields``, the body is sent as
        ``multipart/form-data`` via POST (S3 variant); when ``fields`` is
        absent, the body is sent as raw bytes via PUT (Local variant).
        Raises ``InsForgeError`` on a non-2xx response or on an invalid
        ``fields`` shape. The caller does not need the response body;
        only the status matters.
        """
        upload_url = strategy_body["uploadUrl"]
        fields = strategy_body.get("fields")
        if fields:
            if not isinstance(fields, dict):
                raise InsForgeError(
                    500,
                    {"error": "upload_strategy_invalid_fields", "received": fields},
                )
            transfer = self._client.post(
                upload_url,
                data={**fields, "file": (key, body, content_type)},
            )
        else:
            transfer = self._client.put(
                upload_url,
                content=body,
                headers={"Content-Type": content_type},
            )
        if not transfer.is_success:
            raise InsForgeError(transfer.status_code, _safe_json(transfer))

    def _confirm_upload(self, *, strategy_body: dict[str, Any]) -> Any:
        """Step 3 — POST to the strategy's ``confirmUrl`` to finalise the upload.

        Returns the parsed confirm body (a ``dict`` when the server
        returns JSON; ``None`` for an empty body). Raises
        ``InsForgeError`` when ``confirmUrl`` is absent or on a non-2xx
        response.
        """
        confirm_url = strategy_body.get("confirmUrl")
        if not isinstance(confirm_url, str) or not confirm_url:
            raise InsForgeError(
                500,
                {
                    "error": "upload_strategy_missing_confirm_url",
                    "received": strategy_body,
                },
            )
        confirm = self._client.post(confirm_url)
        if not confirm.is_success:
            raise InsForgeError(confirm.status_code, _safe_json(confirm))
        return _safe_json(confirm)

    def download_object_stream(
        self,
        bucket: str,
        key: str,
    ) -> Iterator[bytes]:
        """Stream the bytes of ``bucket/key`` via the two-step download flow.

        The contract (pinned by operator sentinel evidence):

        1. ``GET /api/storage/buckets/{bucket}/download-strategy/objects/{key}``
           with bearer auth → ``{expiresAt, method, url}``.
        2. ``GET <url>`` with bearer auth, streamed via
           ``httpx.Client.stream`` with a per-chunk
           ``httpx.Timeout(connect=5, read=10, write=5, pool=5)``. The
           ``read=10`` timeout is the safety net that catches a stalled
           stream — without it, a server that returns 200 headers but
           never sends body bytes would hang the route handler
           indefinitely. The presigned URL is self-authenticating but
           the server-side credential is still required per the
           operator contract; both must be sent.

        The returned URL MUST NOT be exposed to the browser/client. The caller
        is expected to wrap this generator in a FastAPI ``StreamingResponse``;
        the consumer decides whether to pre-advance it or stream it directly.

        Network timeouts surface as ``httpx.TimeoutException`` (with
        ``httpx.ReadTimeout`` for stalled streams); non-2xx strategy
        responses raise ``InsForgeError``.
        """
        safe_bucket = _validate_bucket_name(bucket)
        safe_key = _validate_storage_key(key)

        strategy = self._client.get(
            f"/api/storage/buckets/{safe_bucket}/download-strategy/objects/{safe_key}",
        )
        if not strategy.is_success:
            raise InsForgeError(strategy.status_code, _safe_json(strategy))
        strategy_body = _safe_json(strategy)
        if not isinstance(strategy_body, dict) or not isinstance(strategy_body.get("url"), str):
            raise InsForgeError(strategy.status_code, strategy_body)
        download_url = strategy_body["url"]

        # PR4b 4R WARN-1: per-chunk Timeout so a stalled stream cannot
        # hang the route handler. The ``read=10`` budget is per chunk
        # fetch; ``connect=5`` covers the TCP/TLS handshake on the
        # streamed GET; ``write=5`` and ``pool=5`` are symmetric.
        stream_timeout = httpx.Timeout(
            connect=5.0, read=10.0, write=5.0, pool=5.0
        )

        with self._client.stream(
            "GET", download_url, timeout=stream_timeout
        ) as response:
            if not response.is_success:
                # Drain the body so the connection is reusable, then raise.
                try:
                    for _ in response.iter_bytes():
                        pass
                finally:
                    response.close()
                raise InsForgeError(response.status_code, _safe_json(response))
            yield from response.iter_bytes()

    def delete_object(self, bucket: str, key: str) -> None:
        """Delete the object at ``bucket/key``. Idempotent on 404.

        The contract: a single DELETE to
        ``/api/storage/buckets/{bucket}/objects/{key}``. A 404 response
        (object already absent) is treated as success so the operator
        can re-run cleanup without crashing. Any other non-2xx raises
        ``InsForgeError``.
        """
        safe_bucket = _validate_bucket_name(bucket)
        safe_key = _validate_storage_key(key)
        response = self._client.delete(
            f"/api/storage/buckets/{safe_bucket}/objects/{safe_key}",
        )
        if response.status_code == 404:
            return
        if not response.is_success:
            raise InsForgeError(response.status_code, _safe_json(response))

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


# Issue #224: ``key`` (an animal photo filename, e.g. ``NombreFoto``) is
# interpolated directly into storage URL paths (``download_object_stream``,
# ``delete_object``) and sent as a JSON ``filename`` field
# (``_request_upload_strategy``). Unlike ``bucket``, it previously went
# through no format check at all — only a non-emptiness check in the retired
# animal service. This mirrors ``_validate_bucket_name``:
# an allow-list of filename-safe characters (letters, digits, ``_``, ``-``,
# ``.`` for extensions) that still rejects ``/``, ``\``, any ``..``
# segment, and a leading dot (hidden-file / relative-traversal payloads).
_SAFE_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_storage_key(key: str) -> str:
    """Return a safe storage key or raise before any HTTP call.

    Same fail-fast contract as :func:`_validate_bucket_name`: reject
    path separators, ``..`` traversal segments, and a leading dot,
    while still accepting ordinary photo filenames such as
    ``foto123.jpg`` or ``animal-123.png``.
    """
    if not _SAFE_STORAGE_KEY.match(key) or ".." in key or key.startswith("."):
        raise ValueError(
            f"unsafe storage key {key!r}; must match {_SAFE_STORAGE_KEY.pattern} "
            "with no path separators, '..' segments, or leading dot"
        )
    return key


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
