"""Tests for the developer-only admin panel (/admin)."""

from __future__ import annotations

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client


class _FakeInsForge(InsForgeClient):
    def __init__(self) -> None:
        self.list_users_response: list[dict] = []
        self.add_user_response: dict = {
            "id": "u-new",
            "email": "new@example.com",
            "role": "key_user",
            "is_active": True,
            "created_at": "2026-06-17T00:00:00Z",
        }
        self.deactivate_user_response: dict | None = None

    def execute_sql(self, query, params=None):  # type: ignore[override]
        if "ORDER BY created_at DESC" in query:
            return list(self.list_users_response)
        if "INSERT INTO authorized_users" in query and "VALUES" in query:
            return [dict(self.add_user_response)]
        if "SET is_active = false" in query:
            row = self.deactivate_user_response
            return [dict(row)] if row else []
        return []


@pytest.fixture
def fake_insforge() -> _FakeInsForge:
    fake = _FakeInsForge()
    app.dependency_overrides[get_insforge_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as(client: httpx.AsyncClient, secret: str, *, role: str, email: str, user_id: str) -> None:
    """Install a session cookie on the client so the route sees a logged-in user."""
    token = write_session(
        {"email": email, "role": role, "user_id": user_id}, secret=secret
    )
    client.cookies.set(session_cookie_name(), token)


# --- /admin -----------------------------------------------------------------


async def test_admin_redirects_to_login_when_not_authed(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_admin_redirects_to_unauthorized_when_role_not_developer(
    client: httpx.AsyncClient,
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        role="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_admin_renders_user_table_for_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.list_users_response = [
        {
            "id": "u-1",
            "email": "ana@example.com",
            "role": "key_user",
            "is_active": True,
            "created_at": "2026-06-17T00:00:00Z",
        },
        {
            "id": "u-2",
            "email": "eva@example.com",
            "role": "reader",
            "is_active": False,
            "created_at": "2026-06-16T00:00:00Z",
        },
    ]
    _login_as(
        client,
        get_settings().session_secret,
        role="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ana@example.com" in response.text
    assert "eva@example.com" in response.text
    assert "key_user" in response.text


# --- POST /admin/users ------------------------------------------------------


async def test_admin_add_user_inserts_and_redirects(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        role="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await client.post(
        "/admin/users",
        data={"email": "new@example.com", "role": "key_user"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


async def test_admin_add_user_with_invalid_role_redirects_without_calling_sql(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    """An invalid role short-circuits before any SQL is sent."""
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        role="developer",
        email="root@example.com",
        user_id="u-root",
    )
    fake_insforge.add_user_response = {"id": "should-not-be-used"}

    response = await client.post(
        "/admin/users",
        data={"email": "new@example.com", "role": "hacker"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


async def test_admin_add_user_rejects_non_developer(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        role="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await client.post(
        "/admin/users",
        data={"email": "new@example.com", "role": "key_user"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


# --- POST /admin/users/{id}/deactivate -------------------------------------


async def test_admin_deactivate_user_updates_and_redirects(
    client: httpx.AsyncClient, fake_insforge: _FakeInsForge
) -> None:
    from app.core.config import get_settings

    fake_insforge.deactivate_user_response = {
        "id": "u-1",
        "email": "a@b.com",
        "role": "key_user",
        "is_active": False,
    }
    _login_as(
        client,
        get_settings().session_secret,
        role="developer",
        email="root@example.com",
        user_id="u-root",
    )

    response = await client.post(
        "/admin/users/u-1/deactivate", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/admin"


async def test_admin_deactivate_user_rejects_non_developer(
    client: httpx.AsyncClient,
) -> None:
    from app.core.config import get_settings

    _login_as(
        client,
        get_settings().session_secret,
        role="key_user",
        email="ana@example.com",
        user_id="u-ana",
    )

    response = await client.post(
        "/admin/users/u-1/deactivate", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"
