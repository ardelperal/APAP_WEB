"""E2E: every top-level nav item renders its lucide icon (issue #808).

Acceptance criteria from #808:
- On ``/login`` at the desktop viewport, every direct-child ``<a>`` of
  ``<nav id='nav-main'>`` contains exactly one ``<svg>`` carrying
  ``aria-hidden="true"`` and a ~16x16 box, rendered from the inlined
  lucide sprite (``_lucide_nav_sprite.html``).
- The visible label text is unchanged by the icon: the anchor's text
  content is exactly the short label registered in
  ``app/core/nav.py::NAV_ITEMS``. The svg is ``aria-hidden`` so screen
  readers announce only the label.

``/login`` renders the anonymous nav (no session), so the expected set
is ``nav_items_for_role("")`` — the developer-only ``/admin`` item is
correctly absent there.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from app.core.nav import nav_items_for_role

# Desktop viewport, same pinning width as test_nav_no_multiline.py.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}

# The icon box is declared 16x16; allow sub-pixel/border rounding.
ICON_SIZE_TOLERANCE_PX = 2


def _preflight_login_available(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (Google OAuth not configured in dev)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav icon audit cannot run."
        )


def _nav_link_audit(page: Page) -> list[dict]:
    """Return one audit entry per direct-child ``<a>`` of ``#nav-main``.

    Each entry carries ``href``, ``text`` (trimmed text content), and
    ``icons``: the list of ``{ariaHidden, width, height}`` for every
    ``<svg>`` inside the anchor.
    """
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('#nav-main > a')).map(a => {"
        "  return {"
        "    href: a.getAttribute('href'),"
        "    text: a.textContent.trim(),"
        "    icons: Array.from(a.querySelectorAll('svg')).map(s => {"
        "      const r = s.getBoundingClientRect();"
        "      return {"
        "        ariaHidden: s.getAttribute('aria-hidden'),"
        "        width: r.width,"
        "        height: r.height"
        "      };"
        "    })"
        "  };"
        "})"
    )


def test_each_nav_link_renders_one_aria_hidden_16px_icon(
    page: Page, base_url: str
) -> None:
    """Every nav anchor holds exactly one aria-hidden ~16x16 svg icon.

    Exactly one: two icons would double the visual weight; zero means
    the loop lost the ``<svg>`` or the sprite include is missing (a
    dangling ``<use>`` renders a blank box).
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_link_audit(page)
    assert links, "<nav id='nav-main'> must contain at least one direct-child <a>"

    for link in links:
        assert len(link["icons"]) == 1, (
            f"nav link {link['href']!r} must contain exactly one svg icon, "
            f"found {len(link['icons'])}"
        )
        icon = link["icons"][0]
        assert icon["ariaHidden"] == "true", (
            f"nav icon on {link['href']!r} must carry aria-hidden=\"true\" "
            "so screen readers announce only the label"
        )
        assert abs(icon["width"] - 16) <= ICON_SIZE_TOLERANCE_PX, (
            f"nav icon on {link['href']!r} must be ~16px wide, "
            f"got {icon['width']:.2f}px"
        )
        assert abs(icon["height"] - 16) <= ICON_SIZE_TOLERANCE_PX, (
            f"nav icon on {link['href']!r} must be ~16px tall, "
            f"got {icon['height']:.2f}px"
        )


def test_nav_labels_unchanged_by_icons(page: Page, base_url: str) -> None:
    """Rendered (href, label) pairs equal the anonymous nav registry.

    The icon must not leak into the accessible or visible text: the
    anchor's text content is exactly the registered short label, in
    ``NAV_ITEMS`` render order, with the role-gated ``/admin`` absent
    for the anonymous /login page.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_link_audit(page)
    rendered = [(link["href"], link["text"]) for link in links]
    expected = [(item.href, item.label) for item in nav_items_for_role("")]

    assert rendered == expected, (
        f"rendered nav drifted from the registry.\nRendered: {rendered}\n"
        f"Expected: {expected}"
    )
