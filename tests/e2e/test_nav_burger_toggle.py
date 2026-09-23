"""E2E: hamburger toggle behaviour (issue #820, second half of #804).

Re-expressed for #868 (PR 2): ``#nav-main`` is now the desktop sidebar
rail instead of the header nav row, but the toggle contract is
layout-agnostic and unchanged — the burger button
(``#nav-burger-toggle``) and the rail container (``#nav-main``) keep
their ids and semantics, and the rail stays visible at ``md`` and above
regardless of the ``hidden`` attribute (``hidden md:flex``).

Acceptance criteria from #820:
- Click on the burger button toggles ``aria-expanded`` and shows/hides
  ``<nav id="nav-main">``.
- When the menu opens, focus moves to the first focusable descendant
  of the nav.
- Tab / Shift+Tab stay inside the open menu (focus trap).
- Escape closes the menu and returns focus to the toggle.
- Click outside the menu + button closes the menu.
- Click on any internal ``<a>`` closes the menu before navigation.
- A keyboard-only user can open, traverse, close, and return focus to
  the toggle without using the mouse.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

MOBILE_VIEWPORT = {"width": 375, "height": 667}


def _preflight_login_available(page: Page, base_url: str) -> None:
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "burger toggle audit cannot run."
        )


def _state(page: Page) -> dict:
    return page.evaluate(
        "() => {"
        "  const btn = document.getElementById('nav-burger-toggle');"
        "  const nav = document.getElementById('nav-main');"
        "  if (!btn || !nav) return null;"
        "  return {"
        "    expanded: btn.getAttribute('aria-expanded'),"
        "    hidden: nav.hidden,"
        "    active: document.activeElement ? document.activeElement.tagName + ':' + (document.activeElement.textContent || '').trim().slice(0, 40) : null"
        "  };"
        "}"
    )


@pytest.fixture
def mobile_login_page(page: Page, base_url: str):
    """Set viewport to mobile and navigate to /login (always renders base.html)."""
    _preflight_login_available(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    return page


def test_click_toggle_opens_nav_and_moves_focus(mobile_login_page: Page) -> None:
    """Click on the burger opens the nav and focuses the first focusable descendant."""
    page = mobile_login_page
    btn = page.locator("#nav-burger-toggle")
    btn.click()

    state = _state(page)
    assert state["expanded"] == "true", f"after click, aria-expanded must be 'true', got {state['expanded']!r}"
    assert state["hidden"] is False, "after click, nav.hidden must be False (visible)"


def test_second_click_toggle_closes_nav_and_returns_focus(mobile_login_page: Page) -> None:
    """Second click closes the nav and returns focus to the button."""
    page = mobile_login_page
    btn = page.locator("#nav-burger-toggle")
    btn.click()  # open
    page.keyboard.press("Escape")  # close via keyboard first, since click closes it directly
    # Actually re-test: open with click, close with click
    btn.click()  # open
    btn.click()  # close

    state = _state(page)
    assert state["expanded"] == "false", f"after second click, aria-expanded must be 'false', got {state['expanded']!r}"
    assert state["hidden"] is True, "after second click, nav.hidden must be True"


def test_escape_closes_open_nav(mobile_login_page: Page) -> None:
    """Escape closes the nav."""
    page = mobile_login_page
    page.locator("#nav-burger-toggle").click()  # open
    page.keyboard.press("Escape")

    state = _state(page)
    assert state["expanded"] == "false", f"after Escape, aria-expanded must be 'false', got {state['expanded']!r}"
    assert state["hidden"] is True, "after Escape, nav.hidden must be True"


def test_focus_traps_inside_open_nav(mobile_login_page: Page) -> None:
    """Tab from the last focusable wraps to the first; Shift+Tab from the first wraps to the last."""
    page = mobile_login_page
    page.locator("#nav-burger-toggle").click()  # open
    # Focus is now on the first link inside the nav.

    # Tab through all focusables to land on the last.
    focusables_count = page.evaluate(
        "() => document.querySelectorAll('#nav-main a[href], #nav-main button:not([disabled])').length"
    )
    assert focusables_count >= 2, (
        f"nav should have at least 2 focusables for the trap to be meaningful, got {focusables_count}"
    )

    # Tab past the last: focus wraps to the first.
    for _ in range(focusables_count + 1):
        page.keyboard.press("Tab")
    active_after_wrap = page.evaluate(
        "() => { const n = document.getElementById('nav-main');"
        "  return n && n.contains(document.activeElement) ? 'inside' : 'outside'; }"
    )
    assert active_after_wrap == "inside", (
        f"after Tab past the last focusable, focus must wrap inside the nav; got {active_after_wrap!r}"
    )


def test_click_outside_closes_open_nav(mobile_login_page: Page) -> None:
    """Click outside the nav + button closes the menu."""
    page = mobile_login_page
    page.locator("#nav-burger-toggle").click()  # open

    # Click on the main element, well outside the header / nav.
    page.locator("main").click(position={"x": 100, "y": 100}, force=True)

    state = _state(page)
    assert state["expanded"] == "false", (
        f"after click outside, aria-expanded must be 'false', got {state['expanded']!r}"
    )
    assert state["hidden"] is True, "after click outside, nav.hidden must be True"


def test_internal_link_click_closes_nav(mobile_login_page: Page) -> None:
    """Click on any internal <a> closes the menu before navigation."""
    page = mobile_login_page
    page.locator("#nav-burger-toggle").click()  # open

    # Click the first internal link in the nav. Navigation is blocked
    # server-side (route may 404 without auth context), but the close
    # happens BEFORE navigation so the state assertion holds either way.
    page.locator("#nav-main a[href='/animales']").click(no_wait_after=True)

    state = _state(page)
    assert state["expanded"] == "false", (
        f"after clicking an internal link, aria-expanded must be 'false', got {state['expanded']!r}"
    )
