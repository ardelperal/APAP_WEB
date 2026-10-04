"""E2E: logout flow verification.

Issue #124 closure: POST /logout should clear the session cookie and
redirect to /login. The current implementation uses GET /logout which
redirects to / (the original page). This test captures the current
behaviour and pins the redirect chain so any future POST-variant change
is validated against this baseline.

Test strategy:
- Without an active session, /logout still redirects (no-op, no error).
- The session cookie (apap_session) is cleared after the redirect.

Issue #206 partial scope: logout is a public route, no OAuth required.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def _skip_if_oauth_not_configured(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (Google OAuth not configured in dev).

    Mirror of the helper in tests/e2e/test_public_redirects.py — kept local
    so test_logout.py remains self-contained and conftest.py is untouched.
    """
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "the logout redirect chain cannot be observed end-to-end."
        )


def _assert_bounced_to_login(page: Page, response, origin: str) -> None:
    """Assert an anonymous navigation landed on a rendered /login.

    Final-response semantics (issues #1153/#1160): ``page.goto`` returns
    the FINAL response of the redirect chain, so the server-side 302
    surfaces as 200 @ /login; the ``redirected_from`` predecessor pins
    the server-redirect contract (a JS bounce would not have one).
    """
    assert response is not None
    assert response.status == 200, (
        f"{origin} should land on a rendered /login (final response of the redirect "
        f"chain), got {response.status} @ {response.url}"
    )
    assert page.url.endswith("/login"), (
        f"{origin} without session should redirect to /login, got: {page.url}"
    )
    assert response.request.redirected_from is not None, (
        f"{origin} must reach /login through a server redirect, not a client-side bounce"
    )


def test_get_logout_is_not_served_and_clears_nothing(page: Page, base_url: str) -> None:
    """Issue #1076: ``GET /logout`` answers 405 and clears nothing.

    Logout is a state-changing action: it is POST + CSRF only. A
    cross-site top-level navigation (a link to ``/logout``) must not be
    able to clear the session cookie, so GET is intentionally not
    served.
    """
    _skip_if_oauth_not_configured(page, base_url)
    response = page.goto(f"{base_url}/logout", wait_until="domcontentloaded")

    assert response is not None and response.status == 405, (
        f"GET /logout must answer 405 (POST-only route, issue #1076); "
        f"got {response.status if response else None}"
    )
    set_cookie = response.headers.get("set-cookie", "")
    assert "apap_session=" not in set_cookie, (
        f"GET /logout must not clear the session cookie; got Set-Cookie: {set_cookie!r}"
    )


def test_post_logout_without_session_is_refused(page: Page, base_url: str) -> None:
    """Issue #1076: ``POST /logout`` without a session/CSRF token is refused.

    The anonymous-observable contract of the POST-only logout: the CSRF
    middleware refuses the write before the handler runs. The
    authenticated click-through ("Salir" button, POST + hidden CSRF
    token) is pinned at the template level by
    ``tests/test_csrf_form_enumeration.py`` /
    ``tests/test_all_post_forms_have_csrf_input.py``.
    """
    _skip_if_oauth_not_configured(page, base_url)

    response = page.request.post(f"{base_url}/logout", max_redirects=0)
    assert response.status == 403, (
        f"POST /logout without a session/CSRF token must answer 403 "
        f"(issue #1076); got {response.status}"
    )


def test_logout_is_not_reachable_by_navigation(
    page: Page, base_url: str
) -> None:
    """Issue #1076: navigating to ``/logout`` cannot log anyone out.

    The original cross-site logout hazard: a top-level navigation from
    another site used to clear the cookie. Now GET answers 405 without
    touching the session, and an anonymous POST is refused with 403.
    """
    _skip_if_oauth_not_configured(page, base_url)
    # The GET navigation clears nothing (405, pinned above); a protected
    # route afterwards still bounces to /login exactly as without the
    # navigation — anonymous users never had a session.
    page.goto(f"{base_url}/logout", wait_until="domcontentloaded")

    response = page.goto(f"{base_url}/animales", wait_until="domcontentloaded")
    _assert_bounced_to_login(page, response, "/animales after logout navigation")
