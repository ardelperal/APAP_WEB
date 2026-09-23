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

from app.core.nav import (
    NAV_ENTRIES,
    NAV_ITEMS,
    NavGroup,
    NavItem,
    nav_entries_for_role,
    nav_group_hrefs,
    nav_items_for_role,
    resolve_active_nav_href,
)

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
    """Desktop renders the grouped rail; mobile keeps the flat loop (#868).

    Issue #868 (PR 2) replaces the desktop horizontal nav with the
    grouped sidebar rail: a flat ``nav_items`` loop cannot produce a
    group's disclosure control, so ``base.html`` now loops over
    ``nav_entries``. ``base_mobile.html`` still renders the flat
    ``nav_items`` loop until the mobile rail PR of the issue. Both loop
    variables stay ``item`` — the XSS URL-attribute allowlist in
    ``tests/test_xss_audit.py`` pins ``item.href`` / ``item.icon`` /
    ``item.title`` per template.
    """
    desktop = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
    assert "{% for item in nav_entries %}" in desktop, (
        f"{DESKTOP_TEMPLATE.relative_to(REPO_ROOT)} must render the "
        "grouped rail via the Jinja loop over nav_entries (issue #868)."
    )
    mobile = MOBILE_TEMPLATE.read_text(encoding="utf-8")
    assert "{% for item in nav_items %}" in mobile, (
        f"{MOBILE_TEMPLATE.relative_to(REPO_ROOT)} must render the nav via the "
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


# --- Grouped registry (#868) -------------------------------------------------


def test_nav_items_flatten_preserves_exact_order() -> None:
    """``NAV_ITEMS`` flattens ``NAV_ENTRIES`` into the exact 9-href order.

    Compared against an explicit expected list so a future reordering
    of either the groups or the flat registry fails loudly: every
    consumer of the flat view (active-href resolution, sprite parity,
    the XSS URL-attribute allowlist) depends on this sequence.
    """
    expected = [
        "/animales",
        "/entradas",
        "/entradas/batch/new",
        "/casas-acogida",
        "/acogidas",
        "/adopciones",
        "/sanidad",
        "/voluntarios",
        "/admin",
    ]
    assert [item.href for item in NAV_ITEMS] == expected


def test_nav_items_flatten_preserves_item_values() -> None:
    """Each flattened ``NavItem`` IS the grouped registry's item.

    Flattening must contribute the original objects (same href, label,
    icon, title, role), not rebuilt copies that could drift.
    """
    flattened = {item.href: item for item in NAV_ITEMS}
    for entry in NAV_ENTRIES:
        children = entry.children if isinstance(entry, NavGroup) else (entry,)
        for child in children:
            assert flattened[child.href] is child


def test_nav_entries_shape() -> None:
    """``NAV_ENTRIES`` has 5 top-level entries, exactly 2 of them groups."""
    assert len(NAV_ENTRIES) == 5
    groups = [entry for entry in NAV_ENTRIES if isinstance(entry, NavGroup)]
    assert len(groups) == 2
    assert [group.label for group in groups] == ["Entradas", "Acogida"]
    assert [group.icon for group in groups] == ["package-plus", "home"]
    assert [len(group.children) for group in groups] == [2, 4]


def test_nav_entries_for_role_anonymous() -> None:
    """Anonymous keeps Animales, Entradas, Acogida and Voluntarios; drops Admin."""
    entries = nav_entries_for_role("")
    labels = [entry.label for entry in entries]
    assert labels == ["Animales", "Entradas", "Acogida", "Voluntarios"]
    # Both groups survive and keep ALL their children.
    entradas = entries[1]
    acogida = entries[2]
    assert isinstance(entradas, NavGroup)
    assert isinstance(acogida, NavGroup)
    assert [c.href for c in entradas.children] == ["/entradas", "/entradas/batch/new"]
    assert [c.href for c in acogida.children] == [
        "/casas-acogida",
        "/acogidas",
        "/adopciones",
        "/sanidad",
    ]


def test_nav_entries_for_role_developer_drops_nothing() -> None:
    """For ``developer``, NO entry is dropped: identity, labels and order.

    The developer role gates nothing, so the filtered output must equal
    the registry itself — same 5 entries, same order, same labels. This
    pins the "no entry survives/drops differently per role" contract;
    the anonymous counterpart covers the filtering path.
    """
    entries = nav_entries_for_role("developer")
    labels = [entry.label for entry in entries]
    assert labels == ["Animales", "Entradas", "Acogida", "Voluntarios", "Admin"]


def test_nav_entries_for_role_returns_new_group_instances() -> None:
    """Role filtering returns NEW group instances, not the frozen originals.

    Mutation is impossible by construction (``NavGroup`` is frozen, so
    attribute assignment raises ``FrozenInstanceError``); the guarantee
    pinned here is that the helper rebuilds groups instead of reusing
    the registry originals, keeping label/icon and only the surviving
    children (original items, in order).
    """
    for role in ("", "developer"):
        entries = nav_entries_for_role(role)
        registry_groups = [e for e in NAV_ENTRIES if isinstance(e, NavGroup)]
        filtered_groups = [e for e in entries if isinstance(e, NavGroup)]
        assert len(filtered_groups) == len(registry_groups)
        for original, rebuilt in zip(registry_groups, filtered_groups, strict=True):
            assert rebuilt is not original, "filter must rebuild, never reuse"
            assert rebuilt.label == original.label
            assert rebuilt.icon == original.icon
            # Surviving children are the original items, in order.
            assert all(
                any(child is orig_child for orig_child in original.children)
                for child in rebuilt.children
            )
    # Bare NavItem entries are contributed as-is (no copies).
    developer_entries = nav_entries_for_role("developer")
    registry_items = [e for e in NAV_ENTRIES if isinstance(e, NavItem)]
    filtered_items = [e for e in developer_entries if isinstance(e, NavItem)]
    assert filtered_items == registry_items
    assert all(
        a is b for a, b in zip(filtered_items, registry_items, strict=True)
    )


def test_nav_entries_for_role_drops_fully_gated_group(monkeypatch) -> None:
    """A group whose children are ALL role-gated is dropped entirely.

    Built with a synthetic registry so the atom does not depend on the
    real registry containing such a group.
    """
    import app.core.nav as nav_module

    synthetic_registry = (
        NavItem(href="/open", label="Open", icon="x"),
        NavGroup(
            label="Sintetico",
            icon="shield",
            children=(
                NavItem(href="/x", label="X", icon="x", role="developer"),
                NavItem(href="/y", label="Y", icon="y", role="developer"),
            ),
        ),
    )
    monkeypatch.setattr(nav_module, "NAV_ENTRIES", synthetic_registry)
    entries = nav_entries_for_role("")
    assert [entry.label for entry in entries] == ["Open"]
    # The developer still sees the synthetic group with both children.
    developer_entries = nav_entries_for_role("developer")
    synthetic = developer_entries[1]
    assert isinstance(synthetic, NavGroup)
    assert [c.href for c in synthetic.children] == ["/x", "/y"]


def test_nav_entries_for_role_pins_exact_group_children_for_every_role() -> None:
    """Every group's children (count, order, hrefs) survive per role.

    Pins the EXACT children of both groups for BOTH ``""`` and
    ``"developer"`` so dropping or reordering any single child for any
    single role fails loudly (e.g. a trim of Entradas' first child for
    developer only).
    """
    expected_entradas = ["/entradas", "/entradas/batch/new"]
    expected_acogida = [
        "/casas-acogida",
        "/acogidas",
        "/adopciones",
        "/sanidad",
    ]
    for role in ("", "developer"):
        entries = nav_entries_for_role(role)
        groups = [e for e in entries if isinstance(e, NavGroup)]
        assert len(groups) == 2, f"role={role!r}: group count changed"
        entradas, acogida = groups
        assert entradas.label == "Entradas"
        assert acogida.label == "Acogida"
        assert len(entradas.children) == 2, f"role={role!r}: Entradas child count"
        assert len(acogida.children) == 4, f"role={role!r}: Acogida child count"
        assert [c.href for c in entradas.children] == expected_entradas, (
            f"role={role!r}: Entradas children reordered or dropped"
        )
        assert [c.href for c in acogida.children] == expected_acogida, (
            f"role={role!r}: Acogida children reordered or dropped"
        )


def test_every_nav_group_icon_has_a_sprite_symbol() -> None:
    """Every ``NavGroup.icon`` resolves in the inlined lucide sprite.

    Mirrors the ``NavItem`` parity atom: PR 2 will render a
    ``<use href="#nav-icon-<group icon>">`` for each group heading, and
    a typo here would render a dangling reference. Fails loudly at unit
    time instead.
    """
    sprite = SPRITE.read_text(encoding="utf-8")
    for entry in NAV_ENTRIES:
        if not isinstance(entry, NavGroup):
            continue
        pattern = f'<symbol id="nav-icon-{entry.icon}"'
        assert pattern in sprite, (
            f"nav group {entry.label!r} references icon {entry.icon!r} but "
            f"{SPRITE.relative_to(REPO_ROOT)} has no {pattern!r} symbol; "
            "add it there (see lucide-static)."
        )


def test_nav_group_hrefs_returns_children_hrefs_in_order() -> None:
    """``nav_group_hrefs`` yields the child hrefs in group order."""
    groups = [entry for entry in NAV_ENTRIES if isinstance(entry, NavGroup)]
    assert nav_group_hrefs(groups[0]) == ("/entradas", "/entradas/batch/new")
    assert nav_group_hrefs(groups[1]) == (
        "/casas-acogida",
        "/acogidas",
        "/adopciones",
        "/sanidad",
    )


# --- Open-group calculation (issue #868, consumed by the desktop rail) -------


def test_open_group_labels_open_only_the_group_holding_the_active_page() -> None:
    """A path inside a group opens exactly that group and nothing else."""
    from app.core.middleware import _nav_open_group_labels

    assert _nav_open_group_labels("/acogidas") == frozenset({"Acogida"})


def test_open_group_labels_longest_prefix_opens_its_own_group() -> None:
    """A nested page opens its own group (longest-prefix active href).

    ``/entradas/batch/new`` resolves to the ``/entradas/batch/new``
    child (longest prefix), which lives inside the Entradas group — so
    Entradas opens, not Acogida.
    """
    from app.core.middleware import _nav_open_group_labels

    assert _nav_open_group_labels("/entradas/batch/new") == frozenset({"Entradas"})


def test_open_group_labels_top_level_path_opens_no_group() -> None:
    """A top-level active page (e.g. /animales) opens no group."""
    from app.core.middleware import _nav_open_group_labels

    assert _nav_open_group_labels("/animales") == frozenset()


def test_open_group_labels_empty_href_opens_no_group() -> None:
    """No active page (``""`` from ``resolve_active_nav_href``) opens no group."""
    from app.core.middleware import _nav_open_group_labels

    assert _nav_open_group_labels("") == frozenset()


def test_open_group_labels_covers_both_real_groups_and_public_paths() -> None:
    """Both registry groups open for paths inside them; /login opens none."""
    from app.core.middleware import _nav_open_group_labels

    assert _nav_open_group_labels("/entradas") == frozenset({"Entradas"})
    assert _nav_open_group_labels("/casas-acogida") == frozenset({"Acogida"})
    assert _nav_open_group_labels("/login") == frozenset()
