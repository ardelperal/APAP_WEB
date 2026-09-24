"""E2E: nav active-state marker (issue #805, Phase B.3, re-expressed for #868).

Acceptance criteria from #805, re-expressed by #868 (PR 2) for the
sidebar rail:
- The rail link whose href matches the current pathname (or its longest
  matching prefix) receives ``aria-current="page"``. The marker may sit
  at any depth: a nested group child (e.g. "Estancias" on /acogidas)
  gets the same treatment as a top-level item.
- Visual treatment is a filled pill using the EXISTING
  ``--color-primary-dark`` token (``#076FB8``) — asserted via the
  computed ``background-color`` so the pill cannot silently lose its
  fill (the old ``.is-active`` class hook died with the header nav;
  the rail styles the ``aria-current`` attribute directly).
- The marker is always a leaf ``<a>``, never a group's disclosure
  control (``<button>``).
- Longest-prefix match: ``/entradas/batch/new`` activates the "Lote"
  link, not "Entradas".
- The active treatment is applied on first render (no flash of
  unstyled active state).
- Exactly one ``aria-current="page"`` inside ``#nav-main`` (no
  double-activation).

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set. Authenticated
routes are parametrised with explicit skip when the auth middleware
redirects to ``/login``.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

PUBLIC_ROUTES = ("/login",)
AUTH_ROUTES = (
    "/animales",
    "/entradas",
    "/entradas/batch/new",
    "/casas-acogida",
    "/acogidas",
    "/adopciones",
    "/sanidad",
    "/voluntarios",
    "/admin",
)

# Expected active label per route (longest-prefix match).
EXPECTED_ACTIVE_LABEL = {
    "/animales": "Animales",
    "/entradas": "Entradas",
    # Issue #806 renamed the long labels so they fit on one line; the
    # long form now lives in the ``title=`` attribute (see
    # ``tests/test_nav_labels_sync.py`` for the CI-enforced pin
    # between these labels and ``app/core/nav.py::NAV_ITEMS``).
    "/entradas/batch/new": "Lote",
    "/casas-acogida": "Casas",
    "/acogidas": "Estancias",
    "/adopciones": "Adopciones",
    "/sanidad": "Actuaciones",
    "/voluntarios": "Voluntarios",
    "/admin": "Admin",
}


def _preflight_login_available(page: Page, base_url: str) -> None:
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav active-state audit cannot run."
        )


def _skip_if_redirected(page: Page, base_url: str, target: str) -> bool:
    page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if page.url.rstrip("/").endswith("/login") and target != "/login":
        pytest.skip(
            f"route {target!r} redirects to /login without a session; "
            "the active-state mechanism is already covered by unit tests."
        )
        return True
    return False


def _active_label(page: Page) -> str | None:
    return page.evaluate(
        "() => { const a = document.querySelector('#nav-main [aria-current=\"page\"]');"
        "  return a ? a.textContent.trim() : null; }"
    )


# --- public sentinel -----------------------------------------------------


def test_no_active_state_on_login_route(page: Page, base_url: str) -> None:
    """On /login, no nav item is active (login is not in NAV_ITEMS)."""
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    active = _active_label(page)
    assert active is None, (
        f"/login should not mark any nav item as active, got {active!r}"
    )


# --- authenticated-route sentinels (skip on redirect) -------------------


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_active_item_matches_path_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """Each authenticated route marks exactly one nav item as active, with the expected label."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, route):
        return

    active = _active_label(page)
    expected = EXPECTED_ACTIVE_LABEL[route]
    assert active == expected, (
        f"{route!r}: expected active nav label {expected!r}, got {active!r}"
    )


def test_longest_prefix_match_for_batch_new(page: Page, base_url: str) -> None:
    """``/entradas/batch/new`` activates "Lote", not "Entradas"."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/entradas/batch/new"):
        return

    active = _active_label(page)
    assert active == "Lote", (
        f"/entradas/batch/new should activate 'Lote' (longest prefix match), got {active!r}"
    )


def test_active_item_uses_primary_dark_filled_pill(page: Page, base_url: str) -> None:
    """The active rail item is a filled pill in ``--color-primary-dark``.

    ``#076FB8`` is the existing ``--color-primary-dark`` token; no new
    token was introduced for the rail. Asserting the computed
    ``background-color`` (not a class name) pins the visual contract:
    if the pill loses its fill or drifts to another colour, this fails.
    """
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/animales"):
        return

    bg = page.evaluate(
        "() => { const a = document.querySelector('#nav-main [aria-current=\"page\"]');"
        "  return a ? getComputedStyle(a).backgroundColor : null; }"
    )
    assert bg == "rgb(7, 111, 184)", (
        f"active rail item must be a filled pill in --color-primary-dark "
        f"(#076FB8 → rgb(7, 111, 184)), got {bg!r}"
    )


def test_active_marker_is_a_leaf_link_not_a_group_control(
    page: Page, base_url: str
) -> None:
    """The ``aria-current="page""`` marker sits on an ``<a>``, never on a group button.

    A group's disclosure control must never be announced as the current
    page: the marker belongs to the leaf link that matches the path.
    """
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/animales"):
        return

    tag = page.evaluate(
        "() => { const a = document.querySelector('#nav-main [aria-current=\"page\"]');"
        "  return a ? a.tagName : null; }"
    )
    assert tag == "A", (
        f"aria-current='page' must be on a leaf <a>, got <{tag}> "
        "(a group disclosure control must never be marked as current)"
    )


def test_exactly_one_active_item_on_authenticated_routes(
    page: Page, base_url: str
) -> None:
    """Exactly one nav item has ``aria-current=\"page\"`` on /animales (no double-activation)."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/animales"):
        return

    count = page.evaluate(
        "() => document.querySelectorAll('#nav-main [aria-current=\"page\"]').length"
    )
    assert count == 1, (
        f"exactly one nav item must be active, got {count} (double-activation regression)"
    )
