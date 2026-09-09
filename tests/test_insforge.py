"""Tests for the InsForge REST client.

The client is a thin async HTTPX wrapper around the public InsForge REST
API. All tests run against ``httpx.MockTransport`` so the public surface
is pinned without hitting the network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.data_access import BackendError as BackendError, SqlExecutor


def _json_response(status_code: int, body: dict | list) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def test_execute_sql_posts_to_rawsql_endpoint() -> None:
    """``execute_sql`` POSTs to ``/api/database/advance/rawsql`` with the SQL and params."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _json_response(200, [{"id": 1}])

    transport = httpx.MockTransport(handler)
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test_service",
        transport=transport,
    )

    rows = client.execute_sql("SELECT id FROM users WHERE id = $1", [1])

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/database/advance/rawsql")
    assert captured["body"] == {"query": "SELECT id FROM users WHERE id = $1", "params": [1]}
    assert rows == [{"id": 1}]


def test_execute_sql_sends_authorization_bearer_header() -> None:
    """The client sends the service key in the ``Authorization`` header."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return _json_response(200, [])

    transport = httpx.MockTransport(handler)
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test_service",
        transport=transport,
    )

    client.execute_sql("SELECT 1")

    assert captured["auth"] == "Bearer ik_test_service"


def test_execute_sql_raises_insforge_error_on_4xx() -> None:
    """``execute_sql`` raises ``BackendError`` carrying status and body on failure."""
    transport = httpx.MockTransport(
        lambda request: _json_response(403, {"message": "forbidden"})
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError) as exc:
        client.execute_sql("SELECT 1")

    assert exc.value.status_code == 403
    assert exc.value.body == {"message": "forbidden"}


def test_execute_sql_raises_insforge_error_on_5xx() -> None:
    """``execute_sql`` raises ``BackendError`` on 5xx too (caller decides)."""
    transport = httpx.MockTransport(
        lambda request: _json_response(500, {"message": "boom"})
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError):
        client.execute_sql("SELECT 1")


def test_execute_sql_returns_empty_list_on_empty_payload() -> None:
    """``execute_sql`` returns an empty list when the response has no rows."""
    transport = httpx.MockTransport(lambda request: _json_response(200, []))
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    assert client.execute_sql("SELECT * FROM empty_table") == []


def test_execute_sql_accepts_returning_clause_payload() -> None:
    """``execute_sql`` can return inserted/updated rows (RETURNING *)."""
    transport = httpx.MockTransport(
        lambda request: _json_response(200, [{"id": "new-id", "email": "a@b.com"}])
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    rows = client.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol) VALUES ($1, $2) RETURNING id, email",
        ["a@b.com", "developer"],
    )

    assert rows == [{"id": "new-id", "email": "a@b.com"}]


def test_start_google_oauth_builds_pkce_url() -> None:
    """``start_google_oauth`` returns the InsForge Google OAuth URL with PKCE challenge."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return _json_response(
            200,
            {
                "authUrl": (
                    "https://accounts.google.com/o/oauth2/v2/auth"
                    "?client_id=abc&redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Fcallback"
                    "&code_challenge=xyz&scope=openid+email+profile"
                )
            },
        )

    transport = httpx.MockTransport(handler)
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    auth_url = client.start_google_oauth(
        redirect_uri="https://app.example.com/auth/callback",
        code_challenge="xyz",
    )

    assert "/api/auth/oauth/google" in captured["url"]
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Fcallback" in captured["url"]
    assert "code_challenge=xyz" in captured["url"]
    assert auth_url.startswith("https://accounts.google.com/")


def test_exchange_google_oauth_code_returns_token_and_user() -> None:
    """``exchange_google_oauth_code`` POSTs the code and returns the JWT and user payload."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            {
                "token": "jwt-from-insforge",
                "user": {"id": "u-1", "email": "user@example.com"},
            },
        )

    transport = httpx.MockTransport(handler)
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = client.exchange_google_oauth_code(
        code="google-code",
        code_verifier="verifier",
        redirect_uri="https://app.example.com/auth/callback",
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/auth/oauth/google/callback")
    assert captured["body"]["code"] == "google-code"
    assert captured["body"]["code_verifier"] == "verifier"
    assert result.token == "jwt-from-insforge"
    assert result.user.email == "user@example.com"


def test_exchange_google_oauth_code_raises_on_failure() -> None:
    """``exchange_google_oauth_code`` raises on auth failure (4xx)."""
    transport = httpx.MockTransport(
        lambda request: _json_response(401, {"message": "invalid code"})
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError) as exc:
        client.exchange_google_oauth_code(
            code="bad",
            code_verifier="v",
            redirect_uri="https://app.example.com/auth/callback",
        )

    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# InsForge hosted-OAuth-proxy contract (new flow shipped 2026-06-26).
#
# These tests pin the response shape InsForge actually returns today:
#     POST /api/auth/oauth/exchange?client_type=web
#     200 {"user": {...}, "accessToken": "...", "csrfToken": "..."}
#
# Without this test the production OAuth bug (handler expected ?code= but
# InsForge now sends ?insforge_code=) recurred silently — the route test
# mocked the client, the route-level test pinned a wrong shape, and CI
# was green while the live flow was 422-ing every visitor.
# ---------------------------------------------------------------------------


def test_exchange_insforge_oauth_code_posts_to_exchange_endpoint() -> None:
    """``exchange_insforge_oauth_code`` POSTs to the hosted-proxy exchange endpoint.

    Pins: the URL is ``/api/auth/oauth/exchange?client_type=web``, the
    body carries both ``code`` (the ``insforge_code`` from the callback)
    and ``code_verifier`` (the PKCE verifier minted at /login).
    """
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            {
                "user": {"id": "u-1", "email": "user@example.com"},
                "accessToken": "jwt-from-insforge",
                "csrfToken": "csrf-abc",
            },
        )

    transport = httpx.MockTransport(handler)
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    client.exchange_insforge_oauth_code(
        insforge_code="insforge-code-xyz",
        code_verifier="verifier-abc",
    )

    assert captured["method"] == "POST"
    assert "/api/auth/oauth/exchange" in captured["url"]
    assert "client_type=web" in captured["url"]
    assert captured["body"]["code"] == "insforge-code-xyz"
    assert captured["body"]["code_verifier"] == "verifier-abc"


def test_exchange_insforge_oauth_code_returns_user_and_access_token() -> None:
    """``exchange_insforge_oauth_code`` returns the user and the access token.

    Pins the real InsForge response key (``accessToken``, NOT ``token``)
    and the user payload shape. Any future shape change in either
    key will fail this test — preventing the silent contract drift
    that broke production on 2026-06-28.
    """
    transport = httpx.MockTransport(
        lambda request: _json_response(
            200,
            {
                "user": {"id": "u-7", "email": "ardelperal@gmail.com"},
                "accessToken": "jwt-from-insforge",
                "csrfToken": "csrf-abc",
            },
        )
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    result = client.exchange_insforge_oauth_code(
        insforge_code="insforge-code-xyz",
        code_verifier="verifier-abc",
    )

    assert result.token == "jwt-from-insforge"
    assert result.user.id == "u-7"
    assert result.user.email == "ardelperal@gmail.com"


def test_exchange_insforge_oauth_code_raises_on_401_invalid_credentials() -> None:
    """``exchange_insforge_oauth_code`` raises ``BackendError`` on 401.

    Pins the error path so the production ``/auth/callback`` handler
    can catch ``BackendError`` and redirect to /login instead of
    surfacing a 500 to the user.
    """
    transport = httpx.MockTransport(
        lambda request: _json_response(
            401,
            {
                "error": "INVALID_CREDENTIALS",
                "message": "Invalid or expired insforge_code",
                "statusCode": 401,
            },
        )
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError) as exc:
        client.exchange_insforge_oauth_code(
            insforge_code="expired",
            code_verifier="v",
        )

    assert exc.value.status_code == 401
    assert exc.value.body["error"] == "INVALID_CREDENTIALS"


def test_exchange_insforge_oauth_code_raises_when_response_missing_access_token() -> None:
    """The client refuses a 200 that does NOT carry ``accessToken``.

    Guards against a regression where InsForge's response envelope
    changes (e.g. moves the JWT under a different key). The client
    must surface a clear ``BackendError`` instead of silently returning
    an empty token to the route handler — which would issue a session
    cookie with no underlying identity.
    """
    transport = httpx.MockTransport(
        lambda request: _json_response(
            200,
            {
                "user": {"id": "u-1", "email": "user@example.com"},
                # No accessToken / csrfToken — InsForge would not
                # actually do this, but we must not crash on it.
            },
        )
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError) as exc:
        client.exchange_insforge_oauth_code(
            insforge_code="insforge-code-xyz",
            code_verifier="v",
        )

    assert exc.value.status_code == 200


def test_exchange_insforge_oauth_code_raises_when_response_missing_email() -> None:
    """The client refuses a 200 whose ``user`` lacks ``email``.

    The route handler uses ``exchange.user.email`` as the lookup key
    in ``usuarios_autorizados``. If InsForge ever stops returning it,
    every visitor would be bounced to /unauthorized. Catch that here.
    """
    transport = httpx.MockTransport(
        lambda request: _json_response(
            200,
            {
                "user": {"id": "u-1"},  # no email
                "accessToken": "jwt",
            },
        )
    )
    client = LocalPostgresExecutor(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(BackendError):
        client.exchange_insforge_oauth_code(
            insforge_code="insforge-code-xyz",
            code_verifier="v",
        )
