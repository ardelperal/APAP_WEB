"""Regression sentinels for the mobile-first mandate on the primary nav.

Pin the expected layout invariants at three viewports so any future
regression of the responsive collapse surfaces immediately at CI time
rather than as a 1-star App Store review.

The base template's ``<nav>`` renders all module links inline. At
mobile viewports (iPhone SE 375px) it overflows the viewport by
~550px (see the unfixed mobile-first bug, screenshots in
``docs/audits/mobile-menu-overflow-*.png``). These tests capture that
behaviour as failing assertions; once a fix lands (burger menu or
flex-wrap collapse), they should pass without code changes.

Tests in this module rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` (``page``, ``browser_context``, ``base_url``)
and are auto-skipped by the parent conftest when:

- the chromium binary is missing (``playwright install chromium``),
- ``APAP_E2E_SKIP=1`` is set in the environment.

A per-test preflight additionally skips when ``/login`` returns 503
(Google OAuth not configured in dev), matching the pattern already in
``tests/e2e/test_landing.py``.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# --- viewport constants --------------------------------------------------

# iPhone SE (1st gen) — the canonical narrowest mobile target we support.
MOBILE_VIEWPORT = {"width": 375, "height": 667}

# Desktop default — matches docs/design-tokens-apap-actual.md nav width.
DESKTOP_VIEWPORT = {"width": 1280, "height": 800}

# iPad portrait — tablet boundary (Tailwind's md breakpoint).
TABLET_VIEWPORT = {"width": 768, "height": 1024}

# Allow 4px tolerance for sub-pixel rounding at font-rendering edges.
# Computed widths and bounding boxes sometimes drift 1-2px on Chromium
# due to anti-aliasing; 4 is the project-wide convention from
# tests/test_pages.py for layout assertions.
LAYOUT_TOLERANCE_PX = 4

# Public route that renders ``base.html`` without redirecting away.
# ``/login`` is the only base-template-rendering endpoint that is
# always public: it shows the APAP login form with the full nav even
# for anonymous visitors, so it exercises the same header chrome as
# the protected routes without requiring a session cookie.
PUBLIC_ROUTE = "/login"


def _skip_if_login_unavailable(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (OAuth not configured in dev)."""
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav layout cannot be observed end-to-end."
        )


# --- mobile sentinels ----------------------------------------------------


def test_nav_does_not_overflow_on_mobile(page: Page, base_url: str) -> None:
    """At 375px the primary nav must fit within the viewport.

    Fails today (mobile-first bug): the nav renders 7+ items inline and
    extends to x=700+, producing horizontal page scroll that hides the
    Salir button and the right side of the nav on real iPhone SE
    hardware. Once a burger menu or flex-wrap collapse lands, this
    test passes without further changes.
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    nav = page.locator("nav").first
    nav.wait_for(state="visible")
    bbox = nav.bounding_box()
    assert bbox is not None, "nav must be visible at /login"

    right_edge = bbox["x"] + bbox["width"]
    assert right_edge <= MOBILE_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX, (
        f"nav overflows mobile viewport: "
        f"right_edge={right_edge:.0f}px, "
        f"viewport_width={MOBILE_VIEWPORT['width']}px, "
        f"bbox={bbox}"
    )


def test_page_has_no_horizontal_scroll_on_mobile(
    page: Page, base_url: str
) -> None:
    """At 375px the page must not produce horizontal scroll.

    Today the nav overflows and pushes ``document.documentElement.scrollWidth``
    to ~926px, giving the user a horizontal scroll bar they did not ask for
    and hiding content past the right edge. The fix (burger menu OR flex-wrap
    collapse) brings ``scrollWidth`` back to ``clientWidth``.

    Uses ``document.documentElement`` (``<html>``) per the standard scroll
    measurement: ``body.scrollWidth`` in HTML5 returns the body element's
    own width and does NOT account for children that overflow the body
    itself, which is what mobile overflow actually does.
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    scroll_width = page.evaluate(
        "() => document.documentElement.scrollWidth"
    )
    client_width = page.evaluate(
        "() => document.documentElement.clientWidth"
    )
    assert scroll_width <= client_width + LAYOUT_TOLERANCE_PX, (
        f"horizontal page scroll on mobile: "
        f"documentElement.scrollWidth={scroll_width}, "
        f"documentElement.clientWidth={client_width}"
    )


# --- desktop / tablet sentinels ------------------------------------------


def test_nav_renders_inline_on_desktop(page: Page, base_url: str) -> None:
    """At 1280px the nav must render inline (single row, not stacked)."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    nav = page.locator("nav").first
    nav.wait_for(state="visible")
    bbox = nav.bounding_box()
    assert bbox is not None
    # Single-row inline nav at 1280px is ~40px tall; 80px catches a
    # stacked layout or accidental flex-col regression.
    assert bbox["height"] < 80, (
        f"nav is stacked/too tall on desktop: height={bbox['height']:.0f}px"
    )
    assert bbox["x"] + bbox["width"] <= DESKTOP_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX, (
        f"nav overflows desktop viewport: bbox={bbox}"
    )


def test_page_has_no_horizontal_scroll_on_desktop(
    page: Page, base_url: str
) -> None:
    """At 1280px the document body must not produce horizontal scroll.

    Pins the desktop layout as a regression guard against any future
    change that pushes the page past the viewport at the canonical
    desktop width.
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    scroll_width = page.evaluate(
        "() => document.documentElement.scrollWidth"
    )
    client_width = page.evaluate(
        "() => document.documentElement.clientWidth"
    )
    assert scroll_width <= client_width + LAYOUT_TOLERANCE_PX, (
        f"horizontal page scroll on desktop: "
        f"documentElement.scrollWidth={scroll_width}, "
        f"documentElement.clientWidth={client_width}"
    )


def test_nav_fits_at_tablet_boundary(page: Page, base_url: str) -> None:
    """At 768px (Tailwind md) the nav must fit within the viewport.

    The exact rendering at 768px is a product decision (burger or
    inline-reduced); the floor this test pins is "no overflow". Once
    the mobile-first fix lands this is the regression gate that
    catches a too-aggressive breakpoint (e.g. burger up to 1024px).
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(TABLET_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    body_scroll = page.evaluate(
        "() => document.documentElement.scrollWidth"
    )
    assert body_scroll <= TABLET_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX, (
        f"horizontal page scroll at tablet viewport: "
        f"documentElement.scrollWidth={body_scroll}, "
        f"viewport_width={TABLET_VIEWPORT['width']}"
    )
