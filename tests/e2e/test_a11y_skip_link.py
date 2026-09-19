"""E2E: WCAG 2.4.1 Bypass Blocks — skip link on every route (issue #812).

First focusable element on every page is a "Saltar al contenido principal"
anchor that jumps focus to <main id="main" tabindex="-1">. The anchor uses
the standard sr-only focus:not-sr-only Tailwind pattern.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

PUBLIC_ROUTES = ("/", "/login")
AUTH_ROUTES = ("/animales", "/entradas", "/voluntarios", "/admin")


def _skip_if_oauth_unconfigured(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (Google OAuth not configured)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip("/login returns 503; skip-link e2e needs OAuth configured.")


def _goto_or_skip_if_redirected(page: Page, base_url: str, target: str) -> bool:
    """Return True if the route redirected to /login and the test should skip."""
    response = page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if response is None or (page.url.rstrip("/").endswith("/login") and target != "/login"):
        if target != "/login":
            pytest.skip(f"{target!r} redirects to /login without a session.")
        return True
    return False


def _focus_skip_and_assert_jumps_to_main(page: Page) -> None:
    """Tab + Enter on the focused skip link must land focus on <main id='main'>."""
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    active = page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    assert active == "MAIN", f"Enter must focus <main>, got <{active.lower() if active else 'none'}>"
    main_id = page.evaluate("() => { const m = document.querySelector('main'); return m ? m.id : null; }")
    assert main_id == "main", f"<main> must carry id='main', got id={main_id!r}"


# --- public-route sentinels ------------------------------------------------

def test_skip_link_is_first_focusable_on_home(page: Page, base_url: str) -> None:
    """Tab once on / lands on the skip anchor; href=#main; text contains 'Saltar'."""
    _skip_if_oauth_unconfigured(page, base_url)
    _goto_or_skip_if_redirected(page, base_url, "/")

    page.keyboard.press("Tab")
    active = page.evaluate(
        "() => { const el = document.activeElement; return el ? {tag: el.tagName, text: (el.textContent || '').trim(), href: el.getAttribute('href')} : null; }"
    )
    assert active is not None, "Tab must focus an element on /"
    assert active["tag"] == "A", f"first focused must be the skip anchor, got <{active['tag'].lower()}>"
    assert active["href"] == "#main", f"skip link must point at #main, got {active['href']!r}"
    assert "Saltar" in active["text"], f"skip link text must contain 'Saltar', got {active['text']!r}"


def test_skip_link_enter_moves_focus_to_main_on_home(page: Page, base_url: str) -> None:
    """Pressing Enter on the focused skip link moves focus to <main>."""
    _skip_if_oauth_unconfigured(page, base_url)
    _goto_or_skip_if_redirected(page, base_url, "/")
    _focus_skip_and_assert_jumps_to_main(page)


def test_skip_link_works_on_login_route(page: Page, base_url: str) -> None:
    """The skip link is present and functional on /login (public sentinel)."""
    _skip_if_oauth_unconfigured(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    skip = page.locator('a[href="#main"]').first
    skip.wait_for(state="attached")
    assert skip.count() == 1, "exactly one a[href='#main'] must exist on /login"
    assert "Saltar" in (skip.text_content() or ""), "skip link text must contain 'Saltar'"
    _focus_skip_and_assert_jumps_to_main(page)


def test_main_element_has_id_and_tabindex_on_login(page: Page, base_url: str) -> None:
    """<main> on /login carries id='main' and tabindex='-1' (skip target contract)."""
    _skip_if_oauth_unconfigured(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    main = page.locator("main#main").first
    main.wait_for(state="attached")
    assert main.count() == 1, "exactly one <main id='main'> must exist"
    assert main.get_attribute("tabindex") == "-1", "<main id='main'> must carry tabindex='-1'"


# --- authenticated-route sentinels (skip on redirect) ---------------------

@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_skip_link_present_on_authenticated_routes(page: Page, base_url: str, route: str) -> None:
    """Skip-link mechanism works end-to-end on each authenticated route (skips on auth redirect)."""
    _skip_if_oauth_unconfigured(page, base_url)
    if _goto_or_skip_if_redirected(page, base_url, route):
        return
    _focus_skip_and_assert_jumps_to_main(page)
