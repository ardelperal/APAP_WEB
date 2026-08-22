"""First authenticated E2E flow test — exercises the OAuth mock (#598).

Closes the loop on the mock landed in #599: this file drives the
mock end-to-end (POST /e2e/login + subsequent authenticated GET)
and pins the auth → admin slice integration. It is also the
template for future E2E flow tests that need a session cookie
without going through Google OAuth — copy the ``authenticated_page``
fixture verbatim and add the flow-specific assertions below.

Three tests:

- ``test_unauthenticated_admin_redirects_to_login`` — a negative
  case pinning the auth gate. Without a session, ``GET /admin``
  returns 303 to ``/login`` (the ``require_developer_user_redirect``
  dep's redirect target). This is what production does today and
  what every authenticated route must continue to do — a
  regression here would silently let unauthenticated users reach
  the admin panel.
- ``test_authenticated_admin_renders_panel`` — the positive
  contract. POST ``/e2e/login`` with the ``X-E2E-Secret`` header
  mints the session, the browser context picks up the cookie, the
  subsequent ``GET /admin`` returns 200 with the developer panel
  rendered (form for adding users + table of existing users).
- ``test_session_cookie_persists_across_requests`` — the
  cookie contract. After authentication, multiple ``GET /admin``
  requests succeed without re-authenticating; the mock's
  pre-populated auth cache keeps the middleware happy across
  requests without a DB round-trip.

The fixture skips gracefully when ``Settings.e2e_auth_enabled`` is
False (i.e. production / local dev without the env var set). The
unit tests in ``tests/test_e2e_auth.py`` cover the contract directly;
this file covers the contract as observed through a real browser.
"""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import BrowserContext, Page

# Sentinel header name shared with app.core.e2e_auth. Duplicated here
# on purpose: tests/e2e/ does not import from app.core to keep the
# Playwright suite transport-agnostic (the suite might run against a
# production build where the dev module is not importable).
E2E_SECRET_HEADER = "X-E2E-Secret"


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or None if unset.

    CI exports ``APAP_E2E_AUTH_SECRET`` from the workflow's variable
    pool; local dev sets it in the dev environment. ``None`` means
    the mock is not wired and the whole module skips.
    """
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_page(browser_context: BrowserContext, base_url: str) -> Page:
    """A Page with a valid session cookie minted by ``/e2e/login``.

    The flow:

    1. POST ``/e2e/login`` via the browser context's request
       client so the response's ``Set-Cookie`` lands on the
       context (NOT on a separate ``requests`` session, which the
       browser would not see).
    2. Verify the response is 200 + JSON shape ``authenticated: true``
       — the contract that ``tests/test_e2e_auth.py`` pins at the
       unit-test layer.
    3. Hand back a Page bound to the same context so subsequent
       navigations carry the cookie.

    Skips the whole fixture when ``APAP_E2E_AUTH_SECRET`` is unset so
    developers running ``pytest tests/e2e/`` locally without the env
    var get a clear skip rather than a confusing 401 traceback.
    """
    secret = _e2e_secret()
    if secret is None:
        pytest.skip(
            "APAP_E2E_AUTH_SECRET not set — the OAuth mock cannot "
            "authenticate this test. CI sets the variable; local dev "
            "needs to export it to run authenticated E2E flows."
        )

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200, (
        f"/e2e/login must return 200 in the e2e suite, got {response.status}. "
        f"The OAuth mock contract is broken; see tests/test_e2e_auth.py."
    )
    payload = response.json()
    assert payload.get("authenticated") is True, (
        f"/e2e/login must report authenticated: true, got {payload!r}."
    )

    page = browser_context.new_page()
    return page


def test_unauthenticated_admin_redirects_to_login(page: Page, base_url: str) -> None:
    """A request to ``/admin`` without a session is rejected at the auth gate.

    ``require_developer_user_redirect`` (issue #146) sends the
    browser to ``/login`` whenever the cookie is absent. The
    negative case is what protects the admin panel from a session
    regression — the first line of defence, even before the
    ``/login`` 503 ever comes into play.

    Skips when ``/login`` returns 503: that happens when Google
    OAuth is not configured AND the OAuth mock is not enabled (the
    legacy dev-server path). The redirect chain still works — the
    auth dep sent us to ``/login`` — but the landing page is 503,
    so we cannot observe the final URL. The existing
    ``test_login_form`` tests already skip on this condition; this
    test follows the same pattern.
    """
    response = page.goto(f"{base_url}/admin")

    assert response is not None
    if response.status == 503:
        pytest.skip(
            "/admin redirected to /login which returned 503 (OAuth "
            "not configured and mock not enabled); the auth gate is "
            "still doing its job — the existing public-flow E2E "
            "tests cover this scenario via _skip_if_oauth_not_configured."
        )

    # FastAPI's ``RedirectResponse`` lands here as either a 303 (the
    # current pattern, ``RedirectResponse(url, status_code=303)``)
    # or a 307 depending on the route. Both are valid redirects for
    # this endpoint; we accept either rather than pin the status
    # code to one and become a regression on the other.
    assert response.status in (303, 307), (
        f"/admin without auth must redirect, got {response.status}"
    )
    assert "/login" in response.url, (
        f"/admin must redirect to /login, got {response.url}"
    )


def test_authenticated_admin_renders_panel(
    authenticated_page: Page, base_url: str
) -> None:
    """The happy path: mock mints a session, the panel renders.

    This is the contract the rest of the E2E flow tests will
    inherit: hit the mock, navigate to a protected route, expect
    200 + some specific content. The two assertions below pin the
    parts that would silently regress:

    - 200 status (no redirect to /login, no 500 from the template
      adapter).
    - The add-user form's ``action="/admin/users"`` — proves the
      admin panel template is rendering, not some other template
      that happens to return 200.
    """
    response = authenticated_page.goto(f"{base_url}/admin")

    assert response is not None
    assert response.status == 200, (
        f"authenticated /admin must render the panel, got {response.status}"
    )
    body = response.text() or ""
    assert 'action="/admin/users"' in body, (
        "/admin must render the add-user form pointing at /admin/users; "
        "if the template path changed, update this assertion with the "
        "operator's confirmation that the new path is correct."
    )
    # The developer-only nav anchor is rendered by ``base.html`` —
    # its presence proves the auth template (not the public layout)
    # was selected.
    assert "Admin" in body, (
        "authenticated /admin must render the developer nav anchor"
    )


def test_session_cookie_persists_across_requests(
    authenticated_page: Page, base_url: str
) -> None:
    """After the mock sets the cookie, every subsequent request carries it.

    The mock pre-populates the in-process auth cache so the
    middleware accepts the cookie without a DB round-trip. This
    test pins that contract by issuing three consecutive
    authenticated requests and asserting each one succeeds — a
    regression that drops the cookie or skips the cache fill would
    fail on the second or third request.
    """
    for attempt in range(3):
        response = authenticated_page.goto(f"{base_url}/admin")
        assert response is not None
        assert response.status == 200, (
            f"authenticated /admin attempt {attempt + 1}/3 must "
            f"succeed, got {response.status}"
        )
