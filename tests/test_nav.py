"""Unit atoms for the nav registry and the loop-rendered base templates (#808).

Covers the contract that the two base templates now rely on:

- ``resolve_active_nav_href`` picks the longest matching href
  (``/entradas/batch/new`` wins over ``/entradas``) and no longer
  depends on the order of ``NAV_ITEMS`` (matching used to rely on a
  length-DESC sort that was never actually correct; #808 made the
  selection order-independent with ``max(..., key=len)``).
- ``nav_items_for_role`` exposes the programmatic role filter (the
  templates inline the equivalent ``{% if %}`` because the context
  processor cannot know the per-render user).
- Every ``NavItem.icon`` has a matching ``<symbol
  id="nav-icon-<icon>">`` in the inlined lucide sprite, so no anchor
  ever renders a dangling ``<use>`` reference.
- Both base templates render the list with the single Jinja loop and
  no longer carry hand-copied nav anchors (the drift those anchors
  caused is what #808 removes).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.nav import NAV_ITEMS, NavItem, nav_items_for_role, resolve_active_nav_href

REPO_ROOT = Path(__file__).resolve().parents[1]
SPRITE = REPO_ROOT / "app" / "templates" / "_lucide_nav_sprite.html"
DESKTOP_TEMPLATE = REPO_ROOT / "app" / "templates" / "base.html"
MOBILE_TEMPLATE = REPO_ROOT / "app" / "templates" / "base_mobile.html"


def test_exact_match_wins_over_shorter_prefix() -> None:
    """/entradas/batch/new highlights the batch item, not /entradas."""
    assert resolve_active_nav_href("/entradas/batch/new") == "/entradas/batch/new"


def test_shorter_path_matches_its_own_item() -> None:
    """/entradas highlights Entradas (no off-by-one prefix leak)."""
    assert resolve_active_nav_href("/entradas") == "/entradas"


def test_matching_is_order_independent() -> None:
    """A reordered ``NAV_ITEMS`` yields the same active href.

    The pre-#808 implementation returned the first match while iterating
    a list that was only *supposed* to be length-sorted; this atom pins
    the ``max(key=len)`` selection against any future reordering.
    """
    import app.core.nav as nav_module

    paths = [
        "/entradas/batch/new",
        "/entradas",
        "/entradas/batch/new/123",
        "/animales/42/edit",
        "/admin",
        "/login",
    ]
    original = nav_module.NAV_ITEMS
    try:
        nav_module.NAV_ITEMS = tuple(reversed(original))
        for path in paths:
            assert resolve_active_nav_href(path) == _reference_longest_match(
                original, path
            ), f"reordered NAV_ITEMS changed the result for {path!r}"
    finally:
        nav_module.NAV_ITEMS = original


def _reference_longest_match(items: tuple[NavItem, ...], path: str) -> str:
    """Order-independent reference: longest href with exact/prefix match."""
    candidates = [
        item.href
        for item in items
        if path == item.href
        or (item.href != "/" and path.startswith(item.href + "/"))
    ]
    return max(candidates, key=len) if candidates else ""


def test_prefix_match_requires_trailing_slash_boundary() -> None:
    """/entradasbatch does not match /entradas (slash boundary)."""
    assert resolve_active_nav_href("/entradasbatch") == ""


def test_unknown_path_returns_empty() -> None:
    """/login is not a nav item; nothing is active."""
    assert resolve_active_nav_href("/login") == ""


def test_nav_items_for_role_excludes_admin_for_anonymous() -> None:
    """Empty role (anonymous) never sees the developer-only item."""
    hrefs = {item.href for item in nav_items_for_role("")}
    assert "/admin" not in hrefs
    assert len(hrefs) == len(NAV_ITEMS) - 1


def test_nav_items_for_role_includes_admin_for_developer() -> None:
    """The developer role sees every item, /admin included."""
    hrefs = {item.href for item in nav_items_for_role("developer")}
    assert "/admin" in hrefs
    assert len(hrefs) == len(NAV_ITEMS)


def test_nav_items_for_role_preserves_render_order() -> None:
    """The role filter is a subset filter: order matches NAV_ITEMS."""
    developer_items = nav_items_for_role("developer")
    expected = [item.href for item in NAV_ITEMS]
    assert [item.href for item in developer_items] == expected


def test_every_nav_icon_has_a_sprite_symbol() -> None:
    """Every ``NavItem.icon`` resolves in the inlined lucide sprite.

    A missing symbol renders a silent blank square (dangling ``<use>``);
    this atom fails loudly at unit time instead.
    """
    sprite = SPRITE.read_text(encoding="utf-8")
    for item in NAV_ITEMS:
        pattern = f'<symbol id="nav-icon-{item.icon}"'
        assert pattern in sprite, (
            f"nav item {item.href!r} references icon {item.icon!r} but "
            f"{SPRITE.relative_to(REPO_ROOT)} has no {pattern!r} symbol; "
            "add it there (see lucide-static)."
        )


def test_both_templates_render_the_nav_loop() -> None:
    """Both base templates loop over ``nav_items`` (single source of truth)."""
    for path in (DESKTOP_TEMPLATE, MOBILE_TEMPLATE):
        template = path.read_text(encoding="utf-8")
        assert "{% for item in nav_items %}" in template, (
            f"{path.relative_to(REPO_ROOT)} must render the nav via the "
            "Jinja loop over nav_items."
        )


def test_templates_no_longer_carry_literal_nav_anchors() -> None:
    """No hand-copied ``href="/animales"``-style nav anchors remain.

    The literal anchors were the drift source #808 removes: a rename had
    to be applied to two templates by hand. Only the loop may emit them.
    """
    for path in (DESKTOP_TEMPLATE, MOBILE_TEMPLATE):
        template = path.read_text(encoding="utf-8")
        for item in NAV_ITEMS:
            assert f'href="{item.href}"' not in template, (
                f"{path.relative_to(REPO_ROOT)} still carries a literal "
                f"nav anchor for {item.href!r}; the loop over nav_items "
                "is the single render path."
            )


def test_nav_anchors_render_aria_hidden_icons() -> None:
    """Each anchor's inline svg is 16x16 and aria-hidden (label-only SR output)."""
    for path in (DESKTOP_TEMPLATE, MOBILE_TEMPLATE):
        template = path.read_text(encoding="utf-8")
        svg_match = re.search(
            r"<svg[^>]*aria-hidden=\"true\"[^>]*>\s*"
            r"<use href=\"#nav-icon-\{\{ item\.icon \}\}\"",
            template,
        )
        assert svg_match is not None, (
            f"{path.relative_to(REPO_ROOT)} must render an aria-hidden "
            "svg referencing #nav-icon-{{ item.icon }} inside the loop."
        )
        svg_tag = re.search(r"<svg[^>]*class=\"nav-icon[^>]*>", template)
        assert svg_tag is not None, "nav svg must carry the nav-icon class"
        assert 'width="16"' in svg_tag.group(0)
        assert 'height="16"' in svg_tag.group(0)
