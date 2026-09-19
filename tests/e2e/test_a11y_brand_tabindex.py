"""E2E: WCAG 2.4.3 / 4.1.2 — brand link collapsed out of the Tab order.

Issue #818 acceptance criteria (combines #807 + #815):
- The desktop ``<header>`` has exactly one ``<a href="/">`` (the brand).
- The brand ``<a>`` carries ``tabindex="-1"`` so it does not consume the
  first Tab stop on every page.
- The first Tab stop on every authenticated route is a real nav item,
  not the brand.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` (``page``, ``browser_context``, ``base_url``)
and inherit the parent conftest's auto-skip when chromium is missing
or ``APAP_E2E_SKIP=1`` is set. Public routes cover the mechanism;
authenticated routes are parametrised with explicit skip when the auth
middleware redirects to ``/login`` (the same preflight pattern used
by ``test_a11y_skip_link.py`` and ``test_a11y_main_landmark.py``).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

PUBLIC_ROUTES = ("/", "/login")
AUTH_ROUTES = ("/animales", "/entradas", "/voluntarios", "/admin")


def _preflight_login_available(page: Page, base_url: str) -> None:
    """Skip when OAuth is not configured (matches helpers in
    ``test_login_form.py`` and ``test_a11y_skip_link.py``)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "brand-tabindex audit cannot run against an unconfigured login flow."
        )


def _skip_if_redirected(page: Page, base_url: str, target: str) -> bool:
    """Return True (and skip) when the auth middleware redirected to /login."""
    page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if page.url.rstrip("/").endswith("/login") and target != "/login":
        pytest.skip(
            f"route {target!r} redirects to /login without a session; "
            "brand-tabindex mechanism is already covered by public-route tests."
        )
        return True
    return False


def _first_focusable_in_header(page: Page) -> dict:
    """Return the first focusable element inside <header> that is reachable
    via sequential Tab (i.e. ``tabindex != -1``)."""
    return page.evaluate(
        "() => {"
        "  const focusables = Array.from(document.querySelectorAll('header a, header button, header summary, header input'));"
        "  const reachable = focusables.filter(el => {"
        "    const ti = el.getAttribute('tabindex');"
        "    return ti !== '-1';"
        "  });"
        "  const first = reachable[0];"
        "  if (!first) return null;"
        "  return {tag: first.tagName, text: (first.textContent || '').trim(), href: first.getAttribute('href') || null};"
        "}"
    )


def _home_root_link_count(page: Page) -> int:
    """Count ``<a href=\"/\">`` inside ``<header>`` on the current page."""
    return page.evaluate(
        "() => document.querySelectorAll('header a[href=\"/\"]').length"
    )


# --- public-route sentinels ----------------------------------------------


def test_header_has_exactly_one_home_link_on_home(page: Page, base_url: str) -> None:
    """The home page header has exactly one <a href='/'> (the brand)."""
    _preflight_login_available(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    count = _home_root_link_count(page)
    assert count == 1, (
        f"home page <header> must have exactly one <a href='/'>, got {count} "
        "(the previous design had the brand + the 'Inicio' nav item both pointing at /)"
    )


def test_brand_link_has_tabindex_minus_one_on_home(page: Page, base_url: str) -> None:
    """The brand <a href='/'> carries tabindex='-1'."""
    _preflight_login_available(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    tabindex = page.evaluate(
        "() => { const b = document.querySelector('header a[href=\"/\"]');"
        "  return b ? b.getAttribute('tabindex') : null; }"
    )
    assert tabindex == "-1", (
        f"brand link must carry tabindex='-1' so it does not consume the first Tab stop, "
        f"got tabindex={tabindex!r}"
    )


def test_first_tab_stop_is_not_brand_on_home(page: Page, base_url: str) -> None:
    """The first focusable element on / (after Tab once) is not the brand link."""
    _preflight_login_available(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    page.keyboard.press("Tab")
    active = page.evaluate(
        "() => { const a = document.activeElement;"
        "  return a ? {tag: a.tagName, text: (a.textContent || '').trim(), href: a.getAttribute('href') || null} : null; }"
    )
    assert active is not None, "Tab must focus an element on /"
    assert not (active["tag"] == "A" and active["href"] == "/"), (
        f"first Tab stop must not be the brand link, got <{active['tag'].lower()} "
        f"href={active['href']!r} text={active['text']!r}>"
    )


# --- authenticated-route sentinels (skip on redirect) -------------------


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_header_has_exactly_one_home_link_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """Every authenticated route renders exactly one <a href='/'> in <header>."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, route):
        return

    count = _home_root_link_count(page)
    assert count == 1, f"{route!r} <header> must have exactly one <a href='/'>, got {count}"


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_first_focusable_is_real_nav_item_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """On every authenticated route, the first focusable element inside <header> is a nav link (not the brand)."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, route):
        return

    first = _first_focusable_in_header(page)
    assert first is not None, f"{route!r} <header> must have at least one focusable nav element"
    assert not (first["tag"] == "A" and first["href"] == "/"), (
        f"{route!r}: first focusable must not be the brand link, "
        f"got <{first['tag'].lower()} href={first['href']!r} text={first['text']!r}>"
    )
