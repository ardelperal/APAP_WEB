"""Tests for the InsForge REST client.

The client is a thin async HTTPX wrapper around the public InsForge REST
API. All tests run against ``httpx.MockTransport`` so the public surface
is pinned without hitting the network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError


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
    client = InsForgeClient(
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
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test_service",
        transport=transport,
    )

    client.execute_sql("SELECT 1")

    assert captured["auth"] == "Bearer ik_test_service"


def test_execute_sql_raises_insforge_error_on_4xx() -> None:
    """``execute_sql`` raises ``InsForgeError`` carrying status and body on failure."""
    transport = httpx.MockTransport(
        lambda request: _json_response(403, {"message": "forbidden"})
    )
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(InsForgeError) as exc:
        client.execute_sql("SELECT 1")

    assert exc.value.status_code == 403
    assert exc.value.body == {"message": "forbidden"}


def test_execute_sql_raises_insforge_error_on_5xx() -> None:
    """``execute_sql`` raises ``InsForgeError`` on 5xx too (caller decides)."""
    transport = httpx.MockTransport(
        lambda request: _json_response(500, {"message": "boom"})
    )
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(InsForgeError):
        client.execute_sql("SELECT 1")


def test_execute_sql_returns_empty_list_on_empty_payload() -> None:
    """``execute_sql`` returns an empty list when the response has no rows."""
    transport = httpx.MockTransport(lambda request: _json_response(200, []))
    client = InsForgeClient(
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
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    rows = client.execute_sql(
        "INSERT INTO authorized_users (email, role) VALUES ($1, $2) RETURNING id, email",
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
    client = InsForgeClient(
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
    client = InsForgeClient(
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
    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=transport,
    )

    with pytest.raises(InsForgeError) as exc:
        client.exchange_google_oauth_code(
            code="bad",
            code_verifier="v",
            redirect_uri="https://app.example.com/auth/callback",
        )

    assert exc.value.status_code == 401
