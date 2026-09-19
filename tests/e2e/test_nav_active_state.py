"""E2E: nav active-state marker (issue #805, Phase B.3).

Acceptance criteria from #805:
- The nav link whose href matches the current pathname (or its longest
  matching prefix) receives ``aria-current="page"`` and the CSS hook
  class ``is-active``.
- Visual treatment uses primary brand colour (``text-primary``,
  ``border-b-2 border-primary``).
- Longest-prefix match: ``/entradas/batch/new`` activates the
  "Entradas en lote" link, not "Entradas".
- The active treatment is applied on first render (no flash of
  unstyled active state).
- axe-core / Lighthouse ``aria-current`` audit reports zero violations.

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
    "/entradas/batch/new": "Entradas en lote",
    "/casas-acogida": "Casas de acogida",
    "/acogidas": "Estancias de acogida",
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
    """``/entradas/batch/new`` activates "Entradas en lote", not "Entradas"."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/entradas/batch/new"):
        return

    active = _active_label(page)
    assert active == "Entradas en lote", (
        f"/entradas/batch/new should activate 'Entradas en lote' (longest prefix match), got {active!r}"
    )


def test_active_item_has_is_active_css_hook(page: Page, base_url: str) -> None:
    """The active nav item carries the CSS class hook ``is-active``."""
    _preflight_login_available(page, base_url)
    if _skip_if_redirected(page, base_url, "/animales"):
        return

    has_class = page.evaluate(
        "() => { const a = document.querySelector('#nav-main [aria-current=\"page\"]');"
        "  return a ? a.classList.contains('is-active') : false; }"
    )
    assert has_class, "active nav item must carry the .is-active CSS class hook"


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
