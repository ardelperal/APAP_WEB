"""E2E: app still renders with the CSP active (AGENTS.md §23).

The Content-Security-Policy header added by SecurityHeadersMiddleware must
not break any existing page render. If a template or static asset triggers
a CSP violation (e.g. inline <script>, eval, or cross-origin resource),
Playwright's console will surface it as a CSP error message.

These tests verify that:
1. The admin panel (/admin) renders without CSP violation errors.
2. The login page (/login) renders without CSP violation errors.
3. The CSP header is present on every HTTP response.

Tests are skipped when OAuth is not configured (the dev server returns 503
from /login), matching the preflight pattern in ``tests/e2e/test_landing.py``.
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
            "the auth flow cannot be observed end-to-end."
        )


def _assert_no_csp_violations(page: Page) -> None:
    """Assert no CSP violation events were emitted to the browser console.

    Uses Playwright's console event listener to capture messages during
    page load and checks for CSP-related errors.
    """
    csp_violations: list[str] = []

    def on_console(msg) -> None:
        if "Refused to" in msg.text or "Content Security Policy" in msg.text:
            csp_violations.append(msg.text)

    page.on("console", on_console)
    # Re-navigate to trigger console capture (messages are collected from
    # the point the listener is registered).
    page.reload()
    page.remove_listener("console", on_console)

    assert not csp_violations, (
        f"CSP violation(s) detected: {csp_violations}"
    )


def _assert_csp_header(response, expected_csp: str) -> None:
    """Assert the CSP header is present and matches the expected baseline."""
    csp = response.headers.get("content-security-policy") or ""
    assert csp == expected_csp, f"Expected CSP header {expected_csp!r}, got {csp!r}"


BASELINE_CSP = (
    "default-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'"
)


def test_healthz_has_csp_header(page: Page, base_url: str) -> None:
    """/healthz carries the CSP header (public, no auth required)."""
    response = page.goto(f"{base_url}/healthz")
    assert response is not None
    _assert_csp_header(response, BASELINE_CSP)
    _assert_no_csp_violations(page)


def test_login_renders_without_csp_violations(
    page: Page, base_url: str
) -> None:
    """/login renders without CSP violations (inline styles OK, no scripts)."""
    page.goto(f"{base_url}/login")
    _assert_no_csp_violations(page)


def test_admin_panel_renders_without_csp_violations(
    page: Page, base_url: str
) -> None:
    """/admin renders without CSP violations (requires auth — skip if no OAuth)."""
    _skip_if_oauth_not_configured(page, base_url)

    # The admin page requires a session. We can't easily log in in E2E
    # without a real OAuth flow. We visit the page and verify:
    # 1. If redirected to /login -> skip (no session possible in E2E without OAuth)
    # 2. If rendered -> assert no CSP violations
    response = page.goto(f"{base_url}/admin", wait_until="domcontentloaded")
    assert response is not None

    if page.url.endswith("/login"):
        pytest.skip(
            "/admin redirected to /login (no OAuth session available in E2E); "
            "auth-gated CSP coverage verified by unit tests."
        )

    # If we reach /admin, verify no CSP violations
    _assert_no_csp_violations(page)
    _assert_csp_header(response, BASELINE_CSP)


def test_static_css_has_csp_header(page: Page, base_url: str) -> None:
    """Static assets (/static/*) carry the CSP header."""
    # /static/css/output.css is the compiled Tailwind bundle referenced by base.html.
    response = page.goto(f"{base_url}/static/css/output.css")
    assert response is not None
    # Static files return a response; verify CSP is present.
    # The response for CSS might have Content-Type: text/css; the header should still be there.
    assert "content-security-policy" in response.headers, (
        f"Expected CSP header on /static/css/output.css, got headers: {dict(response.headers)}"
    )
