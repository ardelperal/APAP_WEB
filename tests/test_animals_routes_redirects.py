"""Verify the redirect path on a protected route after the reg-7 refactor.

Regla 7: ``require_authorized_user`` now returns a ``RedirectResponse``
(rather than raising ``HTTPException``). Handlers MUST early-return
the response via ``return_early_if_response``.

This file exercises the animales routes without a session to confirm
the early-return pattern is wired in every handler. If any handler
forgets the check, this test will surface the ``AttributeError`` (or
a 500) instead of a clean 302 to /login or /unauthorized.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session


@pytest.mark.asyncio
async def test_animales_redirects_to_login_without_session(
    client: httpx.AsyncClient,
) -> None:
    """GET /animales sin sesion -> 302 a /login."""
    response = await client.get("/animales", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_animales_redirects_to_unauthorized_when_is_authorized_false(
    client: httpx.AsyncClient,
) -> None:
    """GET /animales con sesion pero is_authorized=False -> 302 a /unauthorized."""
    settings = get_settings()
    token = write_session(
        {
            "email": "u@example.com",
            "rol": "key_user",
            "user_id": "u-1",
            "is_authorized": False,
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)

    response = await client.get("/animales", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"
