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

Adding a new nav route means: append a ``NavItem`` to ``NAV_ITEMS``
here (in the position the UI should show it) and add its lucide symbol
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


# Header nav rendered in ``base.html`` and ``base_mobile.html``, in UI
# render order. Matching no longer depends on ordering: ``#808``'
# ``resolve_active_nav_href`` picks the longest matching href with
# ``max(..., key=len)``, so two hrefs may now safely nest as prefixes.
NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem(href="/animales", label="Animales", icon="paw-print"),
    NavItem(href="/entradas", label="Entradas", icon="package-plus"),
    NavItem(
        href="/entradas/batch/new",
        label="Lote",
        icon="layers",
        title="Entradas en lote",
    ),
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
    NavItem(href="/voluntarios", label="Voluntarios", icon="users-round"),
    NavItem(href="/admin", label="Admin", icon="shield", role="developer"),
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
    return tuple(item for item in NAV_ITEMS if not item.role or item.role == role)
