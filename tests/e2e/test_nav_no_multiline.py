"""E2E: header nav links fit on one line at desktop 1440x900 (issue #806).

Acceptance criteria from #806 (Phase B.1, slice #806):
- After the rename, every direct-child ``<a>`` of ``<nav id='nav-main'>``
  has ``boundingClientRect().height <= 30`` at the desktop viewport
  (1440x900) with Tailwind v4 ``text-sm``. The three previously
  wrapping labels ("Entradas en lote" → 2 lines, "Casas de acogida" →
  3 lines, "Estancias de acogida" → 3 lines) now render on a single
  line.
- Each renamed link carries the long-form string in its ``title=``
  attribute (hover tooltip) and renders the short label as visible text.
- None of the three long-form strings leaks as visible nav text (a
  parametrised sentinel pins this against accidental regressions).

The scope is restricted to the direct-child ``<a>`` elements of the
nav container; the brand link and the user block link
("Iniciar sesión" / "Salir") are excluded because they are not nav
items (the brand is the wordmark, the user block is the auth CTA).

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
    """Return one entry per direct-child ``<a>`` of ``<nav id='nav-main'>``.

    Each entry carries ``href``, ``text`` (trimmed visible content),
    ``title`` (the ``title=`` attribute, may be ``None``), and ``height``
    (``getBoundingClientRect().height``). Skips the user-block link
    ("Iniciar sesión" / "Salir") which lives inside a nested ``<div>``
    and is not a nav item.
    """
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('#nav-main > a')).map(a => {"
        "  const r = a.getBoundingClientRect();"
        "  return {"
        "    href: a.getAttribute('href'),"
        "    text: a.textContent.trim(),"
        "    title: a.getAttribute('title'),"
        "    height: r.height"
        "  };"
        "})"
    )


def test_every_nav_link_fits_on_one_line_at_desktop(
    page: Page, base_url: str
) -> None:
    """Every direct-child ``<a>`` of ``<nav id='nav-main'>`` has height <= 30 at 1440x900.

    The ``<= 30`` ceiling corresponds to a single line of ``text-sm``
    (line-height 20px) plus a small tolerance for sub-pixel rounding
    and any leading/trailing inline padding. Before the rename, the
    three offending items measured 40-60px here; after the rename,
    every nav link must collapse to a single line.
    """
    _preflight_login_available(page, base_url)
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    links = _nav_links(page)
    assert links, "<nav id='nav-main'> must contain at least one direct-child <a>"

    for link in links:
        assert link["height"] <= 30, (
            f"nav link {link['href']!r} (label={link['text']!r}) wraps "
            f"to multiple lines: height={link['height']:.2f} > 30"
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
