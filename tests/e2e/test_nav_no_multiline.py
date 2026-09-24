"""E2E: rail nav labels fit on one line at desktop 1440x900 (issue #806, re-expressed for #868).

Acceptance criteria from #806, re-expressed by #868 (PR 2) for the
sidebar rail:
- After the rename, every ``<span>`` label inside a rail anchor
  (``a.rail-item`` top-level link or ``a.rail-child`` nested child of
  ``<nav id='nav-main'>``) renders exactly one text line at the desktop
  viewport (1440x900). The three previously wrapping labels ("Entradas
  en lote" → 2 lines, "Casas de acogida" → 3 lines, "Estancias de
  acogida" → 3 lines) now render on a single line — in the rail they
  are nested children of the Acogida / Entradas groups.
- Each renamed link renders the short label as visible text and carries
  the long-form string in its ``title=`` attribute (hover tooltip).
- None of the three long-form strings leaks as visible nav text (a
  parametrised sentinel pins this against accidental regressions).

The scope is restricted to the rail registry anchors (``.rail-item`` /
``.rail-child``); the brand link, the group disclosure buttons and the
user block / "Ver la web" links are excluded because they are not nav
items from ``NAV_ITEMS``.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` and inherit the parent conftest's auto-skip
when chromium is missing or ``APAP_E2E_SKIP=1`` is set.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# Desktop viewport at which the original three items wrap to multiple
# lines with the long labels. Issue #806 fixes the wrap; the test pins
# the regression at this exact width.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}

RENAMED_ITEMS = (
    # (href, short_label_visible, long_form_title)
    ("/entradas/batch/new", "Lote", "Entradas en lote"),
    ("/casas-acogida", "Casas", "Casas de acogida"),
    ("/acogidas", "Estancias", "Estancias de acogida"),
)

LONG_FORM_STRINGS = (
    "Entradas en lote",
    "Casas de acogida",
    "Estancias de acogida",
)


def _preflight_login_available(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (Google OAuth not configured in dev)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "nav no-multiline audit cannot run."
        )


def _nav_links(page: Page) -> list[dict]:
    """Return one entry per rail anchor (``a.rail-item`` / ``a.rail-child``).

    Group disclosure ``<button>``s, the brand link, the user block and
    the "Ver la web" foot link are excluded because they are not
    ``NAV_ITEMS`` anchors. Each entry carries ``href``, ``text``
    (trimmed visible content), ``title`` (the ``title=`` attribute, may
    be ``None``), ``height`` (``getBoundingClientRect().height`` of the
    anchor), and, when the anchor contains a ``<span>`` label,
    ``span_height`` and ``span_line_height`` in px for the line-count
    assertion.
    """
    return page.evaluate(
        "() => Array.from(document"
        ".querySelectorAll('#nav-main a.rail-item, #nav-main a.rail-child'))"
        ".map(a => {"
        "  const r = a.getBoundingClientRect();"
        "  const span = a.querySelector('span');"
        "  const cs = span ? getComputedStyle(span) : null;"
        "  return {"
        "    href: a.getAttribute('href'),"
        "    text: a.textContent.trim(),"
        "    title: a.getAttribute('title'),"
        "    height: r.height,"
        "    span_height: span ? span.getBoundingClientRect().height : null,"
        "    span_line_height: cs ? parseFloat(cs.lineHeight) : null"
        "  };"
        "})"
    )


def test_every_nav_link_fits_on_one_line_at_desktop(
    page: Page, base_url: str
) -> None:
    """Every ``<span>`` label in ``<nav id='nav-main'>`` renders exactly one text line.

    The primary assertion measures text lines, not the anchor box:
    ``round(span_height / line_height) === 1``. The original ``<= 30``
    anchor-height ceiling was mis-calibrated — a single-line anchor
    measures 36px at 1440x900 (20px line-height of ``text-sm`` + 8px
    ``md:py-2`` top + 8px bottom padding), so it never held in a real
    browser. Before the rename, the three offending items wrapped to
    2-3 text lines here; after the rename, every label must be one.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_links(page)
    assert links, "the rail must contain at least one registry anchor"

    for link in links:
        if link["span_height"] is None:
            continue
        line_height = link["span_line_height"]
        assert line_height and line_height > 0, (
            f"nav link {link['href']!r} has no usable computed line-height"
        )
        lines = round(link["span_height"] / line_height)
        assert lines == 1, (
            f"nav link {link['href']!r} (label={link['text']!r}) wraps "
            f"to {lines} text lines: span_height={link['span_height']:.2f}, "
            f"line_height={line_height:.2f}"
        )
        # Defensive anchor-height check. Measured on real Chromium at
        # 1440x900: one line = 20px (text-sm line-height) + 8px (md:py-2
        # top) + 8px (bottom) = 36px; two lines would be 56px. 50 cleanly
        # separates one line from two without pinning the exact padding
        # (the old <= 30 ceiling never held — see docstring above).
        assert link["height"] < 50, (
            f"nav link {link['href']!r} (label={link['text']!r}) anchor "
            f"is too tall: height={link['height']:.2f} >= 50 suggests "
            "multiple rendered lines"
        )


def test_every_top_level_rail_link_has_a_sixteen_px_aria_hidden_icon(
    page: Page, base_url: str
) -> None:
    """Each top-level rail link renders exactly one 16x16 ``<svg aria-hidden="true">``.

    Decorative nav icons must be sized 16x16 px (accept 15-17 to allow
    sub-pixel rounding) and hidden from assistive technology. Nested
    children (``a.rail-child``) are label-only by design (see
    ``test_nav_icons.py::test_group_children_are_label_only``), so the
    audit is scoped to ``a.rail-item`` anchors.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    icons = page.evaluate(
        "() => Array.from(document.querySelectorAll('#nav-main a.rail-item'))"
        "  .map(a => ({"
        "    href: a.getAttribute('href'),"
        "    svgs: Array.from(a.querySelectorAll('svg')).map(s => ({"
        "      aria_hidden: s.getAttribute('aria-hidden'),"
        "      width: s.getBoundingClientRect().width,"
        "      height: s.getBoundingClientRect().height"
        "    }))"
        "  }))"
    )
    assert icons, "the rail must contain at least one top-level anchor"

    for link in icons:
        assert len(link["svgs"]) == 1, (
            f"nav link {link['href']!r} must contain exactly one <svg>, "
            f"got {len(link['svgs'])}"
        )
        svg = link["svgs"][0]
        assert svg["aria_hidden"] == "true", (
            f"nav icon in {link['href']!r} must have aria-hidden='true', "
            f"got {svg['aria_hidden']!r}"
        )
        assert 15 <= svg["width"] <= 17, (
            f"nav icon width in {link['href']!r} must be ~16px, "
            f"got {svg['width']:.2f}"
        )
        assert 15 <= svg["height"] <= 17, (
            f"nav icon height in {link['href']!r} must be ~16px, "
            f"got {svg['height']:.2f}"
        )


@pytest.mark.parametrize(
    "href,short_label,long_form_title",
    RENAMED_ITEMS,
    ids=[item[0] for item in RENAMED_ITEMS],
)
def test_renamed_item_renders_short_label_and_title(
    page: Page, base_url: str, href: str, short_label: str, long_form_title: str
) -> None:
    """Each renamed nav link renders the short label and carries the long-form title.

    The long-form string is the hover tooltip per the issue #806
    acceptance; the short label is what the user actually sees in the
    chrome. The accessible name remains the short label (the ``title``
    attribute is supplementary, not a substitute per WCAG — see the
    risk register in ``odd/tasks/806-rename-nav-items.md``).
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_links(page)
    match = next((link for link in links if link["href"] == href), None)
    assert match is not None, (
        f"no nav link with href={href!r} in <nav id='nav-main'>"
    )
    assert match["text"] == short_label, (
        f"nav link {href!r} must render short label {short_label!r}, "
        f"got {match['text']!r}"
    )
    assert match["title"] == long_form_title, (
        f"nav link {href!r} must carry title={long_form_title!r}, "
        f"got {match['title']!r}"
    )


@pytest.mark.parametrize("long_form", LONG_FORM_STRINGS)
def test_long_form_string_not_in_nav_link_text(
    page: Page, base_url: str, long_form: str
) -> None:
    """No nav link renders the long-form string as visible text.

    The long-form string survives only in the ``title=`` attribute
    (tooltip). This parametrised sentinel pins the regression so a
    future refactor cannot silently re-introduce the long label in the
    chrome.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_links(page)
    for link in links:
        assert long_form not in link["text"], (
            f"long-form {long_form!r} must not appear as visible nav text, "
            f"but nav link {link['href']!r} renders text={link['text']!r}"
        )
