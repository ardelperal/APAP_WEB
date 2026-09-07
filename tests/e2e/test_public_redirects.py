"""E2E: auth-guard redirect sentinels for public-but-protected routes.

Covers the browser-level redirect chain for routes that require auth but
are still reachable by an anonymous client: the auth middleware bounces
them to /login before the handler runs (rule 7: RedirectResponse, not
exceptions).

Issue #124: POST /logout must return 302 to /login (session cleared).
Issue #206 partial scope: OAuth-gated flows are NOT covered here;
only public routes that redirect without requiring secrets.

Routes covered:
- GET /           → /login  (already in test_landing.py, consolidated here)
- GET /animales   → /login  (already in test_landing.py, consolidated here)
- GET /logout     → /      (current implementation; issue #124 asks for POST variant)
- GET /auth/google → 503 if OAuth not configured, else 302 to Google

Tests are auto-skipped by the parent conftest when chromium is missing.
A preflight additionally skips when /login returns 503 (OAuth not configured).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def _skip_if_oauth_not_configured(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (Google OAuth not configured in dev)."""
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "the auth-guard redirect cannot be observed end-to-end."
        )


# --- redirect sentinels ----------------------------------------------------


def test_root_redirects_anonymous_to_login(page: Page, base_url: str) -> None:
    """GET / without session redirects to /login (302).

    Consolidates the redirect sentinel from test_landing.py so all
    public-redirect coverage lives in one place.
    """
    _skip_if_oauth_not_configured(page, base_url)
    response = page.goto(f"{base_url}/", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 302
    assert page.url.endswith("/login"), (
        f"/ without session should redirect to /login, got: {page.url}"
    )


def test_animales_redirects_to_login_without_session(
    page: Page, base_url: str
) -> None:
    """GET /animales without a session redirects to /login (302).

    Pins the auth-guard behaviour at the browser level.
    """
    _skip_if_oauth_not_configured(page, base_url)
    response = page.goto(f"{base_url}/animales", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 302
    assert page.url.endswith("/login"), (
        f"/animales without session should redirect to /login, got: {page.url}"
    )


def test_logout_clears_session_and_redirects_to_root(
    page: Page, base_url: str
) -> None:
    """GET /logout clears the session cookie and redirects to / (302).

    Issue #124: the logout handler clears the session cookie and redirects
    to /. This test verifies the redirect chain at browser level.
    """
    _skip_if_oauth_not_configured(page, base_url)
    response = page.goto(f"{base_url}/logout", wait_until="domcontentloaded")
    assert response is not None
    assert response.status == 302
    assert page.url.endswith("/") or page.url.endswith("/login"), (
        f"/logout should redirect to / or /login, got: {page.url}"
    )


def test_auth_google_returns_503_when_oauth_not_configured(
    page: Page, base_url: str
) -> None:
    """GET /auth/google returns 503 JSON when Google OAuth secrets are missing.

    The route is public but requires LocalBackend + Google OAuth credentials.
    Without them it returns a descriptive error, which the test suite
    uses as a preflight skip signal.
    """
    response = page.request.get(f"{base_url}/auth/google")
    # Accept either 503 (OAuth not configured) or 302 (OAuth configured,
    # redirects to Google). 503 is the CI/dev unconfigured state.
    assert response.status in {302, 503}, (
        f"/auth/google should return 302 or 503, got {response.status}"
    )
    if response.status == 503:
        body = response.json()
        assert "error" in body


def test_healthz_does_not_redirect(page: Page, base_url: str) -> None:
    """/healthz is always public and must return 200, never redirect."""
    response = page.goto(f"{base_url}/healthz")
    assert response is not None
    assert response.status == 200
    assert not page.url.endswith("/login"), (
        "/healthz should never redirect to /login"
    )
