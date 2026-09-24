"""E2E: every rail entry renders its lucide icon (issue #808, re-expressed for #868).

Acceptance criteria from #808, re-expressed by #868 (PR 2) for the
sidebar rail:
- On ``/login`` at the desktop viewport, every top-level rail anchor
  (``a.rail-item`` inside ``<nav id='nav-main'>``) contains exactly one
  ``svg.nav-icon`` carrying ``aria-hidden="true"`` and a ~16x16 box,
  rendered from the inlined lucide sprite
  (``_lucide_nav_sprite.html``). Group disclosure buttons (also
  ``.rail-item``) carry the same icon plus a chevron, so they are
  audited via ``svg.nav-icon`` count, not total ``svg`` count.
- Nested group children (``a.rail-child``) are label-only per the
  approved rail design: zero svgs.
- The visible label text is unchanged by the icon: every rail anchor's
  text content is exactly the short label registered in
  ``app/core/nav.py::NAV_ITEMS``, in flat registry render order (the
  grouped DOM order IS the flattened order by construction — PR 1
  derives ``NAV_ITEMS`` from ``NAV_ENTRIES``). The role-gated
  ``/admin`` item is correctly absent on the anonymous /login page.

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
    """Return one audit entry per rail anchor (top-level or nested child).

    Selects ``a.rail-item`` (top-level plain links) and ``a.rail-child``
    (nested group children) in document order; group disclosure
    ``<button>``s, the brand link and the "Ver la web" foot link are
    excluded because they are not registry anchors. Each entry carries
    ``cls`` (rail-item or rail-child), ``href``, ``text`` (trimmed text
    content), ``nav_icons`` (the ``svg.nav-icon`` count) and ``icons``:
    the list of ``{ariaHidden, width, height}`` for every ``<svg>``
    inside the anchor.
    """
    return page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main a.rail-item, #nav-main a.rail-child'))"
        ".map(a => {"
        "  return {"
        "    cls: a.classList.contains('rail-item') ? 'rail-item' : 'rail-child',"
        "    href: a.getAttribute('href'),"
        "    text: a.textContent.trim(),"
        "    nav_icons: a.querySelectorAll('svg.nav-icon').length,"
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
    """Every top-level rail anchor holds exactly one aria-hidden ~16x16 icon.

    Exactly one: two icons would double the visual weight; zero means
    the loop lost the ``<svg>`` or the sprite include is missing (a
    dangling ``<use>`` renders a blank box). Group children are
    label-only by design — the dedicated assertion below pins that.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = [link for link in _nav_link_audit(page) if link["cls"] == "rail-item"]
    assert links, "the rail must contain at least one top-level anchor"

    for link in links:
        assert link["nav_icons"] == 1, (
            f"rail link {link['href']!r} must contain exactly one svg.nav-icon "
            f"icon, found {link['nav_icons']}"
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


def test_group_children_are_label_only(page: Page, base_url: str) -> None:
    """Nested rail children (a.rail-child) render no icon at all.

    The approved rail design keeps children text-only so the group's
    icon carries the visual identity; a stray svg inside a child means
    the template leaked the top-level item markup into the nested loop.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    children = [link for link in _nav_link_audit(page) if link["cls"] == "rail-child"]
    assert children, "the rail must contain at least one nested child anchor"

    for link in children:
        assert len(link["icons"]) == 0, (
            f"rail child {link['href']!r} must be label-only, "
            f"found {len(link['icons'])} svg(s)"
        )


def test_nav_labels_unchanged_by_icons(page: Page, base_url: str) -> None:
    """Rendered (href, label) pairs equal the anonymous nav registry.

    The icon must not leak into the accessible or visible text: every
    rail anchor's text content is exactly the registered short label,
    in ``NAV_ITEMS`` render order (grouped DOM order IS the flat
    order), with the role-gated ``/admin`` absent for the anonymous
    /login page.
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
