"""E2E: WCAG 2.4.1 Bypass Blocks — skip link on every authenticated route.

Issue #812 acceptance criteria (verbatim, paraphrased where needed for
the harness): the very first focusable element on every page is a
"Saltar al contenido principal" anchor that jumps focus to ``<main>``.
The link is visually hidden until focused (``sr-only focus:not-sr-only``
Tailwind pattern); ``<main>`` carries ``id="main"`` and
``tabindex="-1"`` so the destination can receive focus without joining
the natural tab order.

This test file pins the mechanism on the public routes that do not
require a session (``/`` and ``/login``). The issue's full matrix also
covers the authenticated routes (``/animales``, ``/entradas``,
``/voluntarios``, ``/admin``); a parametric helper exercises them and
skips the ones that the auth middleware redirects to ``/login`` in the
current environment (matching the preflight pattern already used by
``tests/e2e/test_nav_layout.py`` and ``tests/e2e/test_login_form.py``).

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` (``page``, ``browser_context``, ``base_url``)
and inherit the parent conftest's auto-skip when chromium is missing
or ``APAP_E2E_SKIP=1``.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# Public routes that render the base template without redirecting.
# ``/login`` is the canonical preflight endpoint for this kind of
# layout assertion (always renders ``base.html`` even for anonymous
# visitors). ``/`` is the home page; it is auth-gated in this app,
# so we accept either the rendered landing page or a redirect to
# ``/login`` — the skip link is in ``base.html`` and is therefore
# present in either response.
PUBLIC_ROUTES = ("/", "/login")

# Authenticated routes from the issue's acceptance matrix. The skip
# link lives in ``base.html`` (and ``base_mobile.html``), so if it
# works on a public route it works on every route; the parametrised
# block below only skips when the auth middleware redirects to
# ``/login`` (i.e. the route is gated and we have no session). When
# axe-core lands as a transversal CI gate, this matrix becomes a
# redundant safety net rather than the primary signal.
AUTH_ROUTES = ("/animales", "/entradas", "/voluntarios", "/admin")


def _preflight_login_available(page: Page, base_url: str) -> None:
    """Skip the whole module when OAuth is not configured.

    Mirrors the helper in ``tests/e2e/test_login_form.py`` and
    ``tests/e2e/test_nav_layout.py``: a ``/login`` returning 503 means
    Google OAuth credentials are absent, and the login form (and the
    routes that depend on a session) cannot be exercised end-to-end.
    """
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "skip-link e2e cannot run against an unconfigured login flow."
        )


def _skip_if_redirected_to_login(page: Page, base_url: str, target: str) -> bool:
    """Return True (and skip) when the auth middleware redirected the request.

    Some routes are auth-gated; without a session the middleware
    returns 302 → /login. In that case the rendered HTML is the login
    page, which already has a skip link (covered by the public-route
    test). Skip the auth-route variant with a clear reason so the
    suite stays green without faking a session.
    """
    response = page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if response is None:
        return True
    final_url = page.url
    if final_url.rstrip("/").endswith("/login") and target != "/login":
        pytest.skip(
            f"route {target!r} redirects to /login without a session; "
            "skip-link mechanism is already covered by public-route tests."
        )
        return True  # unreachable, but keeps the type checker happy
    return False


# --- public-route sentinels ----------------------------------------------


def test_skip_link_is_first_focusable_on_home(page: Page, base_url: str) -> None:
    """Pressing Tab once on / lands focus on the skip link.

    The skip link's accessible text starts with "Saltar" (Spanish
    locale). This is the literal text the acceptance criteria
    requests ("Saltar al contenido principal" or locale-equivalent).
    """
    _preflight_login_available(page, base_url)
    _skip_if_redirected_to_login(page, base_url, "/")

    page.keyboard.press("Tab")

    active = page.evaluate(
        "() => {"
        "  const el = document.activeElement;"
        "  return el ? {tag: el.tagName, text: (el.textContent || '').trim(), href: el.getAttribute('href')} : null;"
        "}"
    )
    assert active is not None, "Tab must focus an element on /"
    assert active["tag"] == "A", (
        f"first focused element must be the skip anchor, got <{active['tag'].lower()}>"
    )
    assert active["href"] == "#main", (
        f"skip link must point at #main, got href={active['href']!r}"
    )
    assert "Saltar" in active["text"], (
        f"skip link text must contain 'Saltar', got {active['text']!r}"
    )


def test_skip_link_enter_moves_focus_to_main_on_home(
    page: Page, base_url: str
) -> None:
    """Pressing Enter on the focused skip link moves focus to <main>."""
    _preflight_login_available(page, base_url)
    _skip_if_redirected_to_login(page, base_url, "/")

    page.keyboard.press("Tab")
    page.keyboard.press("Enter")

    active_tag = page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    assert active_tag == "MAIN", (
        f"Enter on the skip link must focus <main>, got <{active_tag.lower() if active_tag else 'none'}>"
    )

    main_id = page.evaluate("() => { const m = document.querySelector('main'); return m ? m.id : null; }")
    assert main_id == "main", (
        f"<main> must carry id='main' as the skip link target, got id={main_id!r}"
    )


def test_skip_link_works_on_login_route(page: Page, base_url: str) -> None:
    """The skip link is present and functional on /login (public sentinel)."""
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    skip = page.locator('a[href="#main"]').first
    skip.wait_for(state="attached")
    assert skip.count() == 1, "exactly one a[href='#main'] must exist on /login"
    skip_text = (skip.text_content() or "").strip()
    assert "Saltar" in skip_text, (
        f"skip link text must contain 'Saltar', got {skip_text!r}"
    )

    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    active_tag = page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    assert active_tag == "MAIN", (
        f"Enter on the focused skip link must focus <main> on /login, "
        f"got <{active_tag.lower() if active_tag else 'none'}>"
    )


def test_main_element_has_id_and_tabindex_on_login(
    page: Page, base_url: str
) -> None:
    """<main> on /login carries id='main' and tabindex='-1'.

    Pins the destination half of the contract: without these two
    attributes the skip link has nowhere to land (no id to scroll to)
    and the anchor cannot receive programmatic focus without joining
    the natural tab order.
    """
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    main_locator = page.locator("main#main").first
    main_locator.wait_for(state="attached")
    assert main_locator.count() == 1, "exactly one <main id='main'> must exist"

    tabindex = main_locator.get_attribute("tabindex")
    assert tabindex == "-1", (
        f"<main id='main'> must carry tabindex='-1' to allow programmatic focus "
        f"without entering the tab order, got tabindex={tabindex!r}"
    )


# --- authenticated-route sentinels (skip on redirect) -------------------


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_skip_link_present_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """The skip link is the first focusable on each authenticated route.

    Skips when the auth middleware redirects to ``/login`` because
    the session cookie is absent; the public-route tests above already
    verify the mechanism on the rendered base template.
    """
    _preflight_login_available(page, base_url)
    if _skip_if_redirected_to_login(page, base_url, route):
        return

    skip = page.locator('a[href="#main"]').first
    skip.wait_for(state="attached")
    assert skip.count() == 1, (
        f"exactly one a[href='#main'] must exist on {route!r}"
    )

    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    active_tag = page.evaluate(
        "() => document.activeElement ? document.activeElement.tagName : null"
    )
    assert active_tag == "MAIN", (
        f"skip-link mechanism must work end-to-end on {route!r}, "
        f"focused <{active_tag.lower() if active_tag else 'none'}>"
    )
