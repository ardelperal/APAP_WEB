"""APAP_WEB — header navigation registry.

Single source of truth for the nav items rendered in ``base.html`` and
``base_mobile.html``. Each entry is a frozen :class:`NavItem` carrying
the href, the short label, the lucide icon symbol suffix, an optional
long-form ``title`` (desktop hover tooltip) and an optional ``role``
gate (``"developer"`` = admin-only).

Issue #805 (Phase B.3): the active item gets ``aria-current="page"``
and a CSS ``is-active`` class hook so the user can see which section
they are on. Issue #808: every item also carries a lucide icon and the
templates render the list with a single Jinja loop over ``nav_items``
(exposed by ``current_path_context_processor``), so the order here IS
the render order in both templates.

Issue #868 (sidebar rail, PR 1 — structure only, no template/DOM
change): nav entries may now be grouped. :data:`NAV_ENTRIES` is the
grouped registry (top-level ``NavItem`` or ``NavGroup`` entries, in UI
render order); ``NAV_ITEMS`` stays the flat, complete tuple the rest
of the codebase reads (``resolve_active_nav_href`` and the
sprite-parity test) and is DERIVED from ``NAV_ENTRIES`` by flattening
groups in order, so the flat render order is unchanged. Note the XSS
URL-attribute allowlist (``tests/test_xss_audit.py``) does NOT read
this registry: it hardcodes the exact Jinja expressions ``item.href``
/ ``item.icon`` / ``item.title``, so the template loop variable must
keep those names when PR 2 renders groups. The grouping metadata is
consumed by a later PR in this issue; this PR introduces only the
model plus its unit tests.

Adding a new nav route means: append a ``NavItem`` to the matching
position inside ``NAV_ENTRIES`` here (top-level or inside the group
the UI should show it in) and add its lucide symbol
to ``app/templates/_lucide_nav_sprite.html``; the context processor and
the template pick it up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    """One header navigation entry.

    ``icon`` is the lucide symbol id suffix in the inlined sprite
    (``app/templates/_lucide_nav_sprite.html`` renders
    ``<symbol id="nav-icon-<icon>">``). ``title`` is the long-form
    tooltip shown on the desktop template; empty string means the
    anchor carries no ``title=`` attribute. ``role`` gates visibility:
    empty string means everyone; any other value means the item only
    renders for users whose role matches it (see the template loop).
    """

    href: str
    label: str
    icon: str
    title: str = ""
    role: str = ""


@dataclass(frozen=True)
class NavGroup:
    """A labelled cluster of nav entries rendered as one rail section.

    Introduced by issue #868: the sidebar rail (a later PR in the issue)
    renders a group as a labelled, icon-headed section containing its
    ``children`` in order, while a bare top-level :class:`NavItem` keeps
    rendering as a standalone anchor. ``icon`` follows the same lucide
    symbol convention as :class:`NavItem.icon` (sprite id suffix).
    Groups are frozen: role filtering always rebuilds a new group with
    the surviving children instead of mutating the registry originals.
    """

    label: str
    icon: str
    children: tuple[NavItem, ...]


# Header nav as grouped registry (issue #868), in UI render order:
# a top-level ``NavItem`` renders standalone; a ``NavGroup`` renders
# its ``children`` as one labelled rail section. ``NAV_ITEMS`` below
# is derived from this tuple, so this is the single source of truth
# for both the flat and the grouped views.
NAV_ENTRIES: tuple[NavItem | NavGroup, ...] = (
    NavItem(href="/animales", label="Animales", icon="paw-print"),
    NavGroup(
        label="Entradas",
        icon="package-plus",
        children=(
            NavItem(href="/entradas", label="Entradas", icon="package-plus"),
            NavItem(
                href="/entradas/batch/new",
                label="Lote",
                icon="layers",
                title="Entradas en lote",
            ),
        ),
    ),
    NavGroup(
        label="Acogida",
        icon="home",
        children=(
            NavItem(
                href="/casas-acogida",
                label="Casas",
                icon="home",
                title="Casas de acogida",
            ),
            NavItem(
                href="/acogidas",
                label="Estancias",
                icon="bed",
                title="Estancias de acogida",
            ),
            NavItem(href="/adopciones", label="Adopciones", icon="heart-handshake"),
            NavItem(href="/sanidad", label="Actuaciones", icon="stethoscope"),
        ),
    ),
    NavItem(href="/voluntarios", label="Voluntarios", icon="users-round"),
    NavItem(href="/admin", label="Admin", icon="shield", role="developer"),
)


# Flat view of the header nav rendered by ``base.html`` and
# ``base_mobile.html`` (and read by ``resolve_active_nav_href`` and
# the nav tests), in UI render order. Derived from ``NAV_ENTRIES`` by
# flattening each group's children in place, so the order here IS the
# grouped render order and a reordering of ``NAV_ENTRIES`` shows up
# here immediately.
NAV_ITEMS: tuple[NavItem, ...] = tuple(
    child
    for entry in NAV_ENTRIES
    for child in (entry.children if isinstance(entry, NavGroup) else (entry,))
)


def _href_matches(href: str, current_path: str) -> bool:
    """Return whether ``href`` is an active-state match for ``current_path``.

    Match rules (matching the issue #805 test plan):
    - ``current_path == href`` → exact match wins.
    - ``current_path.startswith(href + "/")`` → prefix match. The trailing
      slash prevents ``/entradas`` from matching ``/entradasbatch`` or
      any other path that merely starts with the same string.
    - The home ``"/"`` does not match arbitrary paths (otherwise every
      page would render the home as active); it only matches ``"/"`` exactly.

    Extracted as a helper so ``resolve_active_nav_href`` stays a flat
    three-line reduction (kept under the CRAP ratchet baseline of 13.00
    by the issue #808 refactor).
    """
    if current_path == href:
        return True
    if href == "/":
        return False
    return current_path.startswith(href + "/")


def resolve_active_nav_href(current_path: str) -> str:
    """Return the longest ``NAV_ITEMS`` href that is a prefix of ``current_path``.

    Independent of the order of ``NAV_ITEMS`` (issue #808): when several
    hrefs match (e.g. ``/entradas`` and ``/entradas/batch/new``), the
    longest one wins via ``max(key=len)``, so ``/entradas/batch/new``
    is highlighted on its own page.
    """
    candidates = [
        item.href
        for item in NAV_ITEMS
        if _href_matches(item.href, current_path)
    ]
    return max(candidates, key=len) if candidates else ""


def nav_items_for_role(role: str) -> tuple[NavItem, ...]:
    """Return the nav items visible to ``role`` (empty role = anonymous).

    Items whose ``NavItem.role`` is empty render for everyone; the rest
    only render for users whose role matches exactly. The templates
    currently inline this filter over the unfiltered ``NAV_ITEMS``
    (see the role ``{% if %}`` in both base templates) because the
    context processor cannot know the per-render user; this helper is
    the programmatic counterpart for tests and future callers.
    """
    return tuple(item for item in NAV_ITEMS if _role_visible(item, role))


def _role_visible(item: NavItem, role: str) -> bool:
    """Return whether ``item`` renders for ``role`` (empty role = everyone).

    Extracted so :func:`nav_items_for_role` and :func:`nav_entries_for_role`
    apply exactly the same per-item rule instead of restating it, and so each
    of them stays a flat reduction under the CRAP ratchet baseline
    (``scripts/check_crap.py`` requires grade A, CRAP < 6, for new code).
    """
    return not item.role or item.role == role


def _group_for_role(group: NavGroup, role: str) -> NavGroup | None:
    """Return ``group`` rebuilt with its role-visible children, or ``None``.

    ``None`` means every child was role-gated away, so the group itself
    disappears from the rail. A group is always rebuilt rather than mutated:
    :class:`NavGroup` is frozen, and the registry originals must survive a
    filtered read unchanged.
    """
    surviving = tuple(child for child in group.children if _role_visible(child, role))
    if not surviving:
        return None
    return NavGroup(label=group.label, icon=group.icon, children=surviving)


def nav_entries_for_role(role: str) -> tuple[NavItem | NavGroup, ...]:
    """Return the grouped nav entries visible to ``role`` (#868).

    Mirrors :func:`nav_items_for_role` over the grouped registry: a top-level
    :class:`NavItem` renders if it is role-visible (``NavGroup`` itself has no
    ``role``), and a :class:`NavGroup` renders only if at least one child is —
    in that case a NEW group is returned holding just the surviving children,
    and a group whose children are all role-gated away is dropped entirely.
    """
    visible: list[NavItem | NavGroup] = []
    for entry in NAV_ENTRIES:
        if isinstance(entry, NavGroup):
            group = _group_for_role(entry, role)
            if group is not None:
                visible.append(group)
        elif _role_visible(entry, role):
            visible.append(entry)
    return tuple(visible)


def nav_group_hrefs(group: NavGroup) -> tuple[str, ...]:
    """Return the group's child hrefs in order (#868).

    A bare ``(str, ...)`` tuple of ``group.children`` hrefs, for
    template-side consumption in a later PR of this issue. No
    active-state semantics are defined here yet: whichever matching
    rule that PR adopts, it will reuse the module's existing
    longest-prefix-with-slash-boundary semantics
    (:func:`_href_matches`) rather than a naive substring check.
    """
    return tuple(child.href for child in group.children)
