"""E2E: landing page renders with the APAP brand palette.

These tests verify the design tokens from
``docs/design-tokens-apap-actual.md`` are actually applied at runtime
in a real browser. The CSS-only unit tests can't catch a typo in a
Tailwind class name or a missing @theme entry — only the browser can.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def test_landing_loads_and_title_is_apap(page: Page, base_url: str) -> None:
    """GET / returns 200 and the title is the APAP landing title."""
    response = page.goto(f"{base_url}/")
    assert response is not None
    assert response.status == 200
    assert "APAP_WEB" in page.title()


def test_landing_applies_apap_blue_primary_color(page: Page, base_url: str) -> None:
    """The hero gradient uses the APAP primary blue (#0A91EB).

    Computed style on the hero card background must include the APAP
    blue hex. A regression where someone replaces the @theme entry with
    a Tailwind default (e.g. sky-700) flips the color and this test
    fails.
    """
    page.goto(f"{base_url}/")

    # The hero is a div with `bg-gradient-to-br from-primary-dark
    # via-primary to-primary-light` — we grab the first descendant of
    # <main> that has a non-none backgroundImage.
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


def test_landing_badge_uses_apap_orange_accent(page: Page, base_url: str) -> None:
    """The 'Migración Legacy → Web ...' badge uses APAP orange #EE812E."""
    page.goto(f"{base_url}/")

    # The badge is the <span class="bg-accent ..."> inside the hero card.
    # We grab it via its role = "main" so we don't pick up the footer
    # text that also says "Migración Legacy → Web".
    badge = page.get_by_role("main").get_by_text("Migración Legacy")
    badge.wait_for(state="visible")

    color = badge.evaluate("el => getComputedStyle(el).backgroundColor")
    # Computed color is rgb(238, 129, 46) for #EE812E.
    assert "rgb(238, 129, 46)" in color, (
        f"Badge background is not APAP orange #EE812E, got: {color!r}"
    )


def test_landing_navigation_links_visible(page: Page, base_url: str) -> None:
    """The top nav exposes Inicio, Animales, Voluntarios."""
    page.goto(f"{base_url}/")

    nav = page.get_by_role("navigation")
    nav_text = nav.inner_text()
    for label in ("Inicio", "Animales", "Voluntarios"):
        assert label in nav_text, f"Top nav is missing {label!r}: {nav_text!r}"


def test_landing_apap_logo_in_header(page: Page, base_url: str) -> None:
    """The header shows the '🐾 APAP' logo on the left."""
    page.goto(f"{base_url}/")

    logo_link = page.get_by_role("link", name="APAP")
    logo_link.first.wait_for(state="visible")
    # The logo link points to the landing root.
    href = logo_link.first.get_attribute("href")
    assert href in ("/", "/index.html"), f"Logo href is unexpected: {href!r}"


def test_landing_footer_uses_apap_primary_dark(page: Page, base_url: str) -> None:
    """The footer uses the APAP primary-dark blue #076FB8."""
    page.goto(f"{base_url}/")

    footer = page.locator("footer")
    footer.wait_for(state="visible")
    bg = footer.evaluate("el => getComputedStyle(el).backgroundColor")
    # #076FB8 is rgb(7, 111, 184). Accept also gradient endpoint.
    assert "rgb(7, 111, 184)" in bg or "rgb(10, 145, 235)" in bg, (
        f"Footer background is not APAP primary blue family: {bg!r}"
    )


def test_healthz_returns_ok_json(page: Page, base_url: str) -> None:
    """/healthz returns 200 with the standard liveness JSON."""
    response = page.goto(f"{base_url}/healthz")
    assert response is not None
    assert response.status == 200
    body = response.json()
    assert body == {"status": "ok", "app": "APAP_WEB"}


def test_unauthorized_page_renders_friendly_message(
    page: Page, base_url: str
) -> None:
    """GET /unauthorized shows the friendly access-denied card."""
    page.goto(f"{base_url}/unauthorized")

    heading = page.get_by_role("heading")
    assert heading.count() >= 1
    # Look for the dog emoji + a Spanish "no tienes acceso" or similar.
    body_text = page.locator("body").inner_text()
    assert "APAP" in body_text
    assert "🐾" in body_text  # the brand mark should still be visible


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
    assert page.url.endswith("/login"), (
        f"/animales without session should redirect to /login, got: {page.url}"
    )
    assert response is not None
    assert response.status == 302
