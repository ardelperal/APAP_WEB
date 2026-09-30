"""E2E: auth-guard redirect + landing page visual regression.

The landing page is protected — anonymous visitors are bounced to
/login before any marketing copy renders. The dev server uses the
no-lifespan script that returns 503 from /login when Google OAuth
env vars are missing; in that case we cannot observe the redirect
chain end-to-end and the visual regression tests skip.

    In a configured environment (staging, where APAP_GOOGLE_CLIENT_ID is
    set) the login page returns 200 and the visual regression can confirm
    the auth guard stops at the APAP login screen.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def _skip_if_oauth_not_configured(page: Page, base_url: str) -> None:
    """Skip the test when /login returns 503 (Google OAuth not configured).

    Several e2e tests rely on the protected-route auth chain working
    end-to-end. In CI without OAuth credentials the dev server returns
    a JSON 503 from /login, which masks the auth flow. Mirror the
    preflight-skip pattern used by ``test_animales_redirects_to_login_without_session``
    so CI stays green and the visual regression only runs where the
    full stack is wired.
    """
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "the auth-guard / OAuth flow cannot be observed end-to-end."
        )


def _assert_bounced_to_login(page: Page, response, origin: str) -> None:
    """Assert an anonymous navigation was redirected to a rendered /login.

    Playwright's ``page.goto`` returns the FINAL response of the
    redirect chain, so a server-side 302 to /login surfaces as a 200
    response whose URL is /login — ``response.status == 302`` is
    unobservable for server redirects (issue #1153). The redirect must
    still have happened at the HTTP level: the final request carries a
    ``redirected_from`` predecessor. A client-side (JS) bounce would
    not, so this assertion pins the server-redirect contract (rule 7:
    redirects are ``RedirectResponse``, not exceptions).
    """
    assert response is not None
    assert response.status == 200, (
        f"{origin} should land on a rendered /login (final response of "
        f"the redirect chain), got {response.status} @ {response.url}"
    )
    assert page.url.endswith("/login"), (
        f"{origin} without session should redirect to /login, got: {page.url}"
    )
    assert response.request.redirected_from is not None, (
        f"{origin} must reach /login through a server redirect, not a "
        "client-side bounce"
    )


def test_landing_redirects_anonymous_users_to_login(
    page: Page, base_url: str
) -> None:
    """GET / is protected — anonymous visitors are bounced to /login.

    Pins the auth-guard behavior at the landing page. The marketing
    modules list (Animales, Voluntarios, Entradas) must not leak to
    unauthenticated probers before the OAuth flow.
    """
    _skip_if_oauth_not_configured(page, base_url)

    response = page.goto(f"{base_url}/", wait_until="domcontentloaded")
    assert response is not None
    assert response.status in {200, 302}
    assert page.url.endswith("/login"), (
        f"/ without session should redirect to /login, got: {page.url}"
    )


def test_login_applies_apap_blue_primary_color(page: Page, base_url: str) -> None:
    """The public login page uses the APAP primary blue (#0A91EB).

    The operational dashboard at / is protected, so anonymous Playwright
    checks must validate the public auth surface instead of private home
    content. Server-side tests cover the authenticated dashboard render.
    """
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    hero_handle = page.evaluate_handle(
        "() => Array.from(document.querySelectorAll('main *'))"
        ".find(el => getComputedStyle(el).backgroundImage !== 'none')"
    )
    bg_image = hero_handle.evaluate("el => getComputedStyle(el).backgroundImage")
    bg_image = bg_image.lower().replace(" ", "")
    # The gradient is built from --color-primary (#0A91EB) and lighter
    # tones. Accept any of the three primary-family blues in the stack.
    assert (
        "rgb(10,145,235)" in bg_image  # #0A91EB
        or "rgb(7,111,184)" in bg_image  # #076FB8 (primary-dark, gradient end)
    ), f"Hero background does not include an APAP blue: {bg_image!r}"


def test_login_page_renders_the_configured_auth_entry_point(
    page: Page, base_url: str
) -> None:
    """The login page renders the auth entry point matching the enabled flow.

    Two deployed config branches exist (issue #1153):

    - ``APAP_AUTH_ENABLE_MAGIC_LINK=true``: ``login.html`` renders the
      magic-link form posting to ``/auth/magic/start`` (#1005).
    - Flag off (OAuth configured): the template renders no form at all;
      the InsForge-era "Entrar con Gmail" link was removed (#728) and
      its absence is pinned by ``tests/test_auth_flow.py``.

    Branching on the rendered DOM keeps the test meaningful under
    either config; no branch is vacuous.
    """
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    magic_form = page.locator("#magic-link-form")
    if magic_form.count() == 1:
        assert magic_form.get_attribute("action") == "/auth/magic/start"
        assert magic_form.get_attribute("method") == "post"
        email_input = magic_form.locator('input[type="email"][name="email"]')
        assert email_input.count() == 1
        email_input.wait_for(state="visible")
        submit = magic_form.locator('button[type="submit"]')
        assert submit.count() == 1
        assert submit.inner_text().strip() == "Enviar enlace"
    else:
        # Flag off: no form renders; the removed Gmail entry (#728)
        # must not reappear.
        assert page.get_by_role("link", name="Entrar con Gmail").count() == 0
        assert page.locator('a[href="/auth/google"]').count() == 0


def test_landing_navigation_links_visible(page: Page, base_url: str) -> None:
    """After anonymous / navigation, the rail nav still renders.

    The anonymous chrome (sidebar rail, issue #868) shows the brand
    block, the registry top-level labels and the session entry. The
    old "Inicio" item no longer exists — the brand block replaced it
    in ``NAV_ENTRIES`` — so the pinned labels are the current registry
    contract (issue #1153).
    """
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/")

    nav = page.get_by_role("navigation")
    nav_text = nav.inner_text()
    for label in ("APAP", "Animales", "Voluntarios", "Iniciar sesión"):
        assert label in nav_text, f"Top nav is missing {label!r}: {nav_text!r}"


def test_landing_apap_logo_in_header(page: Page, base_url: str) -> None:
    """The header shows the '🐾 APAP' logo on the left."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/")

    logo_link = page.get_by_role("link", name="APAP")
    logo_link.first.wait_for(state="visible")
    # The logo link points to the protected operational root.
    href = logo_link.first.get_attribute("href")
    assert href in ("/", "/index.html"), f"Logo href is unexpected: {href!r}"


def test_landing_footer_uses_apap_primary_dark(page: Page, base_url: str) -> None:
    """The footer uses the APAP primary-dark blue #076FB8."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/")

    footer = page.locator("footer")
    footer.wait_for(state="visible")
    bg = footer.evaluate("el => getComputedStyle(el).backgroundColor")
    # #076FB8 is rgb(7, 111, 184). Accept also gradient endpoint.
    assert "rgb(7, 111, 184)" in bg or "rgb(10, 145, 235)" in bg, (
        f"Footer background is not APAP primary blue family: {bg!r}"
    )


def test_healthz_returns_ok_json(page: Page, base_url: str) -> None:
    """The deployed liveness contract at /healthz holds. Always public.

    The deployed handler (``app/main.py``) returns four keys:
    ``status``/``app``/``revision``/``storage``. Pinning the exact dict
    snapshot made the test fail on every contract addition (issue
    #1153); the documented fields are asserted instead, mirroring the
    contract shape of ``tests/e2e_ci/test_application_smoke.py``.
    """
    response = page.goto(f"{base_url}/healthz")
    assert response is not None
    assert response.status == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "APAP_WEB"
    assert isinstance(body.get("revision"), str) and body["revision"]
    assert body.get("storage") in {"up", "down", "unconfigured"}


def test_unauthorized_redirects_to_login_for_anonymous(
    page: Page, base_url: str
) -> None:
    """/unauthorized is only for users with a deactivated session.

    Anonymous visitors must be bounced to /login — the denial copy is
    only meaningful after the auth flow has placed a session cookie in
    the browser (the auth callback sends deactivated users here).
    """
    _skip_if_oauth_not_configured(page, base_url)
    response = page.goto(f"{base_url}/unauthorized", wait_until="domcontentloaded")
    _assert_bounced_to_login(page, response, "/unauthorized")


def test_unauthorized_renders_friendly_message_with_session(
    page: Page, base_url: str
) -> None:
    """With a deactivated session cookie, /unauthorized shows the denial copy.

    The dev server doesn't accept arbitrary session cookies (the secret
    is fixed at startup), so this test only asserts the redirect-to-login
    behavior. In staging a follow-up test could mint a deactivated
    session cookie via the test fixture helpers and assert the full copy.
    """
    _skip_if_oauth_not_configured(page, base_url)
    # Without a valid session cookie the page is still bounced; the
    # behaviour with a deactivated cookie is verified by unit tests in
    # tests/test_pages.py::test_unauthorized_renders_html.
    response = page.goto(f"{base_url}/unauthorized", wait_until="domcontentloaded")
    _assert_bounced_to_login(page, response, "/unauthorized")


def test_animales_redirects_to_login_without_session(
    page: Page, base_url: str
) -> None:
    """GET /animales without a session redirects to /login (302).

    Pins the auth-guard behavior at the browser level: any client that
    tries to reach a protected route without a valid session is sent
    to /login (rule 7: redirects are RedirectResponse, not exceptions).

    Skipped if the dev server doesn't have Google OAuth credentials
    configured — in that case /login returns 503 with the
    "Google OAuth no esta configurado" JSON error, which would mask
    the auth-guard behavior we want to test.
    """
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "the auth-guard redirect can't be observed end-to-end."
        )

    response = page.goto(f"{base_url}/animales", wait_until="domcontentloaded")
    _assert_bounced_to_login(page, response, "/animales")
