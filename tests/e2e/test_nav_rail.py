"""E2E: desktop sidebar rail structure (issue #868, PR 2).

Acceptance criteria from #868 (PR 2):
- At most five top-level entries in the rail (the anonymous rail shows
  four — the developer-only ``/admin`` is role-gated away; an
  authenticated session shows all five).
- A disclosure control (``<button>`` with ``aria-expanded`` +
  ``aria-controls`` pointing at an existing ``<ul>``) exists ONLY on
  the two ``NavGroup`` entries (``Entradas``, ``Acogida``); plain items
  render as links and never carry the disclosure affordance.
- The group containing the active page renders EXPANDED, so the active
  item is never hidden behind a closed control; the other group stays
  collapsed.
- Exactly one element inside ``#nav-main`` carries
  ``aria-current="page"`` and it is a leaf ``<a>``, never a group's
  disclosure control.
- The rail foot carries a ``Ver la web`` link to
  ``https://www.apap-alcala.org/`` with ``rel="noopener"``.

Authenticated assertions use the ``/e2e/login`` mock (the same
``X-E2E-Secret`` contract as ``tests/e2e/test_admin_authenticated.py``;
the helper is duplicated here on purpose — ``tests/e2e/`` does not
import from ``app.core`` and ``conftest.py`` stays out of this PR's
edit surfaces).

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import BrowserContext, Page

from app.core.nav import NAV_ENTRIES, NavGroup, nav_entries_for_role

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}

# Sentinel header name shared with app.core.e2e_auth. Duplicated here
# on purpose: tests/e2e/ does not import from app.core to keep the
# Playwright suite transport-agnostic.
E2E_SECRET_HEADER = "X-E2E-Secret"

EXTERNAL_SITE_URL = "https://www.apap-alcala.org/"


def _preflight_login_available(page: Page, base_url: str) -> None:
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "rail structure audit cannot run."
        )


def _e2e_secret() -> str | None:
    """Return the test-suite shared secret, or None if unset."""
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_page(browser_context: BrowserContext, base_url: str) -> Page:
    """A Page with a valid session cookie minted by ``/e2e/login``.

    Same flow as ``tests/e2e/test_admin_authenticated.py``: POST the
    shared secret so the context receives the session cookie, then hand
    back a Page bound to that context. Skips when
    ``APAP_E2E_AUTH_SECRET`` is unset.
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
        f"/e2e/login must return 200 in the e2e suite, got {response.status}."
    )
    payload = response.json()
    assert payload.get("authenticated") is True, (
        f"/e2e/login must report authenticated: true, got {payload!r}."
    )

    return browser_context.new_page()


def _top_level_entries(page: Page) -> list[dict]:
    """Return the rail's DIRECT top-level entries (anchors + group buttons).

    Group children live inside the group's own ``<ul>`` so they are NOT
    direct children of ``#nav-main`` — that nesting is what keeps the
    top-level count at five.
    """
    return page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main > a.rail-item, #nav-main > button.rail-item'))"
        ".map(el => ({"
        "  tag: el.tagName,"
        "  label: el.textContent.trim(),"
        "  ariaExpanded: el.getAttribute('aria-expanded'),"
        "  ariaControls: el.getAttribute('aria-controls')"
        "}))"
    )


def _goto_and_skip_on_redirect(page: Page, base_url: str, target: str) -> bool:
    """Navigate and return True (skip) when auth middleware redirected."""
    page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if page.url.rstrip("/").endswith("/login") and target != "/login":
        pytest.skip(
            f"route {target!r} redirects to /login without a session; "
            "the authenticated rail structure cannot be observed."
        )
        return True
    return False


# --- anonymous rail (public /login) --------------------------------------


def test_rail_has_at_most_five_top_level_entries(page: Page, base_url: str) -> None:
    """The anonymous rail shows exactly the anonymous registry, capped at five.

    ``/login`` renders without a session, so the developer-only
    ``/admin`` entry is gated away and the count equals
    ``nav_entries_for_role("")`` (4). The ``<= 5`` bound is the hard
    product cap from the approved design; a sixth top-level entry means
    someone added a registry entry without grouping it.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    entries = _top_level_entries(page)
    expected = nav_entries_for_role("")
    assert len(entries) == len(expected) <= 5, (
        f"rail must render exactly the {len(expected)} anonymous top-level "
        f"entries (never more than 5), got {len(entries)}: {entries}"
    )


def test_disclosure_controls_exist_only_on_groups(page: Page, base_url: str) -> None:
    """Chevron/disclosure affordance only on the two groups, never on links.

    Every ``NavGroup`` in the anonymous registry renders a ``<button>``
    with ``aria-expanded`` + ``aria-controls`` resolving to an existing
    ``<ul>`` inside the rail; every plain ``NavItem`` renders an
    ``<a>`` with NO ``aria-expanded`` attribute at all.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    entries = _top_level_entries(page)
    expected_groups = [
        e for e in nav_entries_for_role("") if isinstance(e, NavGroup)
    ]

    buttons = [e for e in entries if e["tag"] == "BUTTON"]
    anchors = [e for e in entries if e["tag"] == "A"]

    assert len(buttons) == len(expected_groups), (
        f"exactly the {len(expected_groups)} registry groups may render a "
        f"disclosure control, got {len(buttons)}: {buttons}"
    )
    for button in buttons:
        assert button["ariaExpanded"] in ("true", "false"), (
            f"group control {button['label']!r} must declare aria-expanded"
        )
        assert button["ariaControls"], (
            f"group control {button['label']!r} must declare aria-controls"
        )
        controls = page.evaluate(
            "(id) => { const el = document.getElementById(id);"
            "  return el && el.tagName === 'UL'"
            "    && document.getElementById('nav-main').contains(el); }",
            button["ariaControls"],
        )
        assert controls, (
            f"group control {button['label']!r} aria-controls must point "
            "at a <ul> inside the rail"
        )
    for anchor in anchors:
        assert anchor["ariaExpanded"] is None, (
            f"plain rail link {anchor['label']!r} must not carry the "
            "disclosure affordance (no aria-expanded)"
        )


def test_no_group_is_expanded_without_an_active_page(
    page: Page, base_url: str
) -> None:
    """On /login no group renders expanded (no active page behind a control).

    ``/login`` is not a nav item, so no group contains the active page;
    every disclosure control must start collapsed.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    expanded = page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main button[aria-expanded]'))"
        ".map(b => b.getAttribute('aria-expanded'))"
    )
    assert expanded and all(state == "false" for state in expanded), (
        f"no group may render expanded on /login, got {expanded}"
    )


def test_rail_foot_links_to_the_external_site(page: Page, base_url: str) -> None:
    """``Ver la web`` points at apap-alcala.org with rel="noopener"."""
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    foot = page.evaluate(
        "() => { const a = document.querySelector('a[href=\"https://www.apap-alcala.org/\"]');"
        "  if (!a) return null;"
        "  return { text: a.textContent.trim(), rel: a.getAttribute('rel'),"
        "    target: a.getAttribute('target'),"
        "    insideRail: document.getElementById('nav-main').contains(a) }; }"
    )
    assert foot is not None, "the rail foot must carry the external site link"
    assert "Ver la web" in foot["text"], f"foot link text drifted: {foot!r}"
    assert foot["insideRail"], "the external link must live inside the rail"
    assert foot["target"] == "_blank", (
        f"external link must open in a new tab, got target={foot['target']!r}"
    )
    assert foot["rel"] is not None and "noopener" in foot["rel"].split(), (
        f"external link must carry rel=\"noopener\", got rel={foot['rel']!r}"
    )


# --- authenticated rail (e2e login mock) ----------------------------------


def test_authenticated_rail_shows_all_five_top_level_entries(
    authenticated_page: Page, base_url: str
) -> None:
    """An authenticated rail renders every registry entry, capped at five."""
    _preflight_login_available(authenticated_page, base_url)
    if _goto_and_skip_on_redirect(authenticated_page, base_url, "/animales"):
        return

    entries = _top_level_entries(authenticated_page)
    assert len(entries) == len(NAV_ENTRIES) <= 5, (
        f"authenticated rail must render all {len(NAV_ENTRIES)} top-level "
        f"entries, got {len(entries)}: {entries}"
    )


def test_group_containing_active_page_renders_expanded(
    authenticated_page: Page, base_url: str
) -> None:
    """On /acogidas the Acogida group is expanded; the other stays collapsed.

    The active child (``/acogidas`` → "Estancias") lives inside the
    Acogida group, so that group MUST render expanded — the active item
    must never be hidden behind a closed control — while Entradas stays
    collapsed.
    """
    _preflight_login_available(authenticated_page, base_url)
    if _goto_and_skip_on_redirect(authenticated_page, base_url, "/acogidas"):
        return

    buttons = authenticated_page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main button[aria-controls]'))"
        ".map(b => ({ controls: b.getAttribute('aria-controls'),"
        "  expanded: b.getAttribute('aria-expanded'),"
        "  label: b.textContent.trim() }))"
    )
    by_label = {b["label"]: b for b in buttons}
    assert set(by_label) == {
        g.label for g in NAV_ENTRIES if isinstance(g, NavGroup)
    }, f"unexpected disclosure controls: {sorted(by_label)}"

    open_groups = [
        label for label, b in by_label.items() if b["expanded"] == "true"
    ]
    assert open_groups == ["Acogida"], (
        f"on /acogidas exactly the Acogida group must render expanded, "
        f"got {open_groups}"
    )

    # The expanded group's <ul> is genuinely visible (not hidden).
    panel_hidden = authenticated_page.evaluate(
        "(id) => document.getElementById(id).hidden", by_label["Acogida"]["controls"]
    )
    assert panel_hidden is False, (
        "the expanded group's child list must not carry the hidden attribute"
    )


def test_exactly_one_aria_current_on_a_leaf(authenticated_page: Page, base_url: str) -> None:
    """Exactly one ``aria-current="page"`` inside the rail, on an ``<a>`` leaf.

    Never on a group's disclosure control, and never doubled (a second
    marker would announce two pages as current).
    """
    _preflight_login_available(authenticated_page, base_url)
    if _goto_and_skip_on_redirect(authenticated_page, base_url, "/acogidas"):
        return

    markers = authenticated_page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main [aria-current=\"page\"]'))"
        ".map(el => ({ tag: el.tagName, href: el.getAttribute('href') }))"
    )
    assert len(markers) == 1, (
        f"exactly one aria-current='page' allowed in the rail, got {markers}"
    )
    assert markers[0]["tag"] == "A", (
        f"the active marker must be a leaf <a>, got <{markers[0]['tag']}>"
    )
    assert markers[0]["href"] == "/acogidas", (
        f"the active marker must be the page's own link, got {markers[0]!r}"
    )
