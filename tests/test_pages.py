"""Tests for protected top-level HTML routes."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session


def _login_as_authorized_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "user@example.com",
            "rol": "key_user",
            "user_id": "u-user",
            "is_authorized": True,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_unauthorized_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "inactive@example.com",
            "rol": "key_user",
            "user_id": "u-inactive",
            "is_authorized": False,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


async def test_index_renders_for_anonymous_users(
    client: httpx.AsyncClient,
) -> None:
    """``GET /`` is the marketing landing page and must be public.

    Anonymous visitors see the APAP brand landing (hero, migration
    badge, navigation, footer) before deciding whether to log in.
    Bouncing them to /login would hide the org's mission copy and
    break the e2e landing suite (which expects 200 + brand content).

    The authenticated app routes (``/animales``, ``/entradas``,
    ``/voluntarios``, ``/admin``) remain protected by the middleware.
    """
    response = await client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Brand mark + nav are present in the landing template.
    assert "🐾" in response.text
    assert "APAP_WEB" in response.text


async def test_index_renders_html(client: httpx.AsyncClient) -> None:
    """``GET /`` returns an HTML page rendered from base.html + index.html."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_index_links_compiled_css(client: httpx.AsyncClient) -> None:
    """The landing page links the compiled Tailwind CSS asset."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert "/static/css/output.css" in response.text


async def test_index_mentions_app_name(client: httpx.AsyncClient) -> None:
    """The landing page shows the application name from settings."""
    _login_as_authorized_user(client)

    response = await client.get("/")

    assert "APAP_WEB" in response.text


async def test_unauthorized_renders_for_anonymous_users(
    client: httpx.AsyncClient,
) -> None:
    """The access-denied page is public so anonymous visitors can read it.

    Previously the handler redirected anonymous users to /login, but the
    page is a friendly info card with no app data — bouncing anonymous
    visitors away made the denial copy unreachable after the auth
    middleware landed. Now /unauthorized renders 200 with the denial
    copy for everyone, matching the e2e landing suite.
    """
    response = await client.get("/unauthorized", follow_redirects=False)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no autorizado" in response.text.lower()


@pytest.mark.parametrize(
    "path",
    [
        "/animales",
        "/animales/abc-123/update",
        "/entradas",
        "/entradas/ent-123/update",
        "/voluntarios",
    ],
)
async def test_protected_form_posts_redirect_anonymous_before_validation(
    client: httpx.AsyncClient,
    path: str,
) -> None:
    """Malformed anonymous POSTs must hit auth before FastAPI form validation."""
    response = await client.post(path, data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize(
    "path",
    [
        "/animales",
        "/entradas",
        "/voluntarios",
    ],
)
async def test_protected_form_posts_redirect_unauthorized_sessions_before_validation(
    client: httpx.AsyncClient,
    path: str,
) -> None:
    """Inactive sessions should reach /unauthorized before form validation."""
    _login_as_unauthorized_user(client)

    response = await client.post(path, data={}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"


async def test_unauthorized_renders_html(client: httpx.AsyncClient) -> None:
    """Authenticated-but-inactive users can see the access-denied copy."""
    _login_as_unauthorized_user(client)

    response = await client.get("/unauthorized")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "no autorizado" in response.text.lower()


async def test_unauthorized_links_compiled_css(client: httpx.AsyncClient) -> None:
    """The unauthorized page links the compiled Tailwind CSS asset."""
    _login_as_unauthorized_user(client)

    response = await client.get("/unauthorized")

    assert "/static/css/output.css" in response.text
