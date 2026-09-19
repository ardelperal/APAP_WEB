"""E2E: responsive nav structure — one ``<nav id="nav-main">``, burger button hides below md.

Issue #819 (first half of the split #804) acceptance criteria:
- The header has exactly one ``<nav id="nav-main">``.
- The button ``<button id="nav-burger-toggle" aria-expanded="false"
  aria-controls="nav-main">Menú</button>`` exists below md and is hidden
  at md and above.
- The nav list is hidden below md by default; at md and above it shows
  inline.

This slice is structural only — the toggle JS lands in #820. Until then,
mobile users cannot open the menu (the button does nothing); the slice
ships dead-in-the-water on mobile by design.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

MOBILE_VIEWPORT = {"width": 375, "height": 667}
DESKTOP_VIEWPORT = {"width": 1280, "height": 800}


def _preflight_login_available(page: Page, base_url: str) -> None:
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav structure audit cannot run."
        )


def _button(page: Page) -> dict:
    return page.evaluate(
        "() => { const b = document.getElementById('nav-burger-toggle');"
        "  if (!b) return null;"
        "  return {display: getComputedStyle(b).display, expanded: b.getAttribute('aria-expanded'), controls: b.getAttribute('aria-controls')};"
        "}"
    )


def _nav(page: Page) -> dict:
    return page.evaluate(
        "() => { const n = document.getElementById('nav-main');"
        "  if (!n) return null;"
        "  return {display: getComputedStyle(n).display, label: n.getAttribute('aria-label')};"
        "}"
    )


def test_single_nav_landmark_on_home(page: Page, base_url: str) -> None:
    """The header has exactly one <nav id='nav-main'> (no legacy <details>)."""
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    navs_in_header = page.evaluate(
        "() => document.querySelectorAll('header nav').length"
    )
    nav_main = page.evaluate("() => document.getElementById('nav-main') ? 1 : 0")
    assert navs_in_header == 1, (
        f"header must render exactly one <nav>, got {navs_in_header} (legacy <details>-burger is gone)"
    )
    assert nav_main == 1, "header must contain an element with id='nav-main'"


def test_burger_button_is_visible_on_mobile_and_hidden_on_desktop(
    page: Page, base_url: str
) -> None:
    """The burger button shows on mobile and hides on desktop."""
    _preflight_login_available(page, base_url)

    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    mobile_button = _button(page)
    assert mobile_button is not None, "burger button must be present in the DOM"
    assert mobile_button["display"] != "none", (
        f"burger button must be visible at mobile viewport, got display={mobile_button['display']!r}"
    )
    assert mobile_button["expanded"] == "false", (
        f"burger button must declare aria-expanded='false', got {mobile_button['expanded']!r}"
    )
    assert mobile_button["controls"] == "nav-main", (
        f"burger button must aria-controls='nav-main', got {mobile_button['controls']!r}"
    )

    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.reload(wait_until="domcontentloaded")
    desktop_button = _button(page)
    assert desktop_button is not None
    assert desktop_button["display"] == "none", (
        f"burger button must be hidden at desktop viewport, got display={desktop_button['display']!r}"
    )


def test_nav_main_is_hidden_on_mobile_and_inline_on_desktop(
    page: Page, base_url: str
) -> None:
    """The single nav is hidden on mobile (until #820 lands the toggle) and inline on desktop."""
    _preflight_login_available(page, base_url)

    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    mobile_nav = _nav(page)
    assert mobile_nav is not None, "nav#nav-main must be present in the DOM"
    assert mobile_nav["display"] == "none", (
        f"nav#nav-main must be hidden at mobile viewport until #820, got display={mobile_nav['display']!r}"
    )
    assert mobile_nav["label"] == "Menú principal", (
        f"nav#nav-main must carry aria-label='Menú principal', got {mobile_nav['label']!r}"
    )

    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.reload(wait_until="domcontentloaded")
    desktop_nav = _nav(page)
    assert desktop_nav is not None
    assert desktop_nav["display"] != "none", (
        f"nav#nav-main must be visible at desktop viewport, got display={desktop_nav['display']!r}"
    )
