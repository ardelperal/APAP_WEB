"""E2E: additional responsive layout sentinels for breakpoint coverage.

Extends ``test_nav_layout.py`` with viewports that were not yet covered:
- 1024px (desktop-small, between tablet 768 and full desktop 1280)
- 1920px (full HD, wider-than-default desktop)

Issue #206: these are public-route layout sentinels, no OAuth required.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# --- viewport constants --------------------------------------------------

DESKTOP_SMALL_VIEWPORT = {"width": 1024, "height": 768}
FULL_HD_VIEWPORT = {"width": 1920, "height": 1080}

# Allow 4px tolerance for sub-pixel rounding (project-wide convention).
LAYOUT_TOLERANCE_PX = 4

# Public route that renders base.html chrome without redirect.
PUBLIC_ROUTE = "/login"


def _skip_if_login_unavailable(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (OAuth not configured in dev)."""
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav layout cannot be observed end-to-end."
        )


# --- 1024px sentinels (desktop-small) -----------------------------------


def test_nav_fits_within_desktop_small_viewport(
    page: Page, base_url: str
) -> None:
    """At 1024px the primary nav must not overflow the viewport."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(DESKTOP_SMALL_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    nav = page.locator("nav").first
    nav.wait_for(state="visible")
    bbox = nav.bounding_box()
    assert bbox is not None, "nav must be visible at /login"

    right_edge = bbox["x"] + bbox["width"]
    assert right_edge <= DESKTOP_SMALL_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX, (
        f"nav overflows 1024px viewport: right_edge={right_edge:.0f}px, "
        f"viewport_width={DESKTOP_SMALL_VIEWPORT['width']}px"
    )


def test_no_horizontal_scroll_at_desktop_small(
    page: Page, base_url: str
) -> None:
    """At 1024px the page must not produce horizontal scroll."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(DESKTOP_SMALL_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    scroll_width = page.evaluate(
        "() => document.documentElement.scrollWidth"
    )
    client_width = page.evaluate(
        "() => document.documentElement.clientWidth"
    )
    assert scroll_width <= client_width + LAYOUT_TOLERANCE_PX, (
        f"horizontal page scroll at 1024px: "
        f"scrollWidth={scroll_width}, clientWidth={client_width}"
    )


# --- 1920px sentinels (full HD) ----------------------------------------


def test_nav_fits_within_full_hd_viewport(page: Page, base_url: str) -> None:
    """At 1920px the primary nav must not overflow the viewport."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(FULL_HD_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    nav = page.locator("nav").first
    nav.wait_for(state="visible")
    bbox = nav.bounding_box()
    assert bbox is not None, "nav must be visible at /login"

    right_edge = bbox["x"] + bbox["width"]
    assert right_edge <= FULL_HD_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX, (
        f"nav overflows 1920px viewport: right_edge={right_edge:.0f}px, "
        f"viewport_width={FULL_HD_VIEWPORT['width']}px"
    )


def test_no_horizontal_scroll_at_full_hd(page: Page, base_url: str) -> None:
    """At 1920px the page must not produce horizontal scroll."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(FULL_HD_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    scroll_width = page.evaluate(
        "() => document.documentElement.scrollWidth"
    )
    client_width = page.evaluate(
        "() => document.documentElement.clientWidth"
    )
    assert scroll_width <= client_width + LAYOUT_TOLERANCE_PX, (
        f"horizontal page scroll at 1920px: "
        f"scrollWidth={scroll_width}, clientWidth={client_width}"
    )


def test_nav_is_single_row_at_full_hd(page: Page, base_url: str) -> None:
    """At 1920px the nav renders as a single row (not stacked)."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(FULL_HD_VIEWPORT)
    page.goto(f"{base_url}{PUBLIC_ROUTE}", wait_until="domcontentloaded")

    nav = page.locator("nav").first
    nav.wait_for(state="visible")
    bbox = nav.bounding_box()
    assert bbox is not None
    # Single-row nav is < 80px tall; stacked layout would be 120+px.
    assert bbox["height"] < 80, (
        f"nav appears stacked at 1920px: height={bbox['height']:.0f}px"
    )
