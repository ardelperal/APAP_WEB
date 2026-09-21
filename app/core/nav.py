"""APAP_WEB — header navigation registry.

Single source of truth for the nav items rendered in ``base.html`` and
``base_mobile.html``. The list is ordered by ``href`` length DESCENDING
so that ``is_active(request.url.path)`` returns the longest matching
prefix (``/entradas/batch/new`` wins over ``/entradas`` when both are
eligible).

Issue #805 (Phase B.3): the active item gets ``aria-current="page"``
and a CSS ``is-active`` class hook so the user can see which section
they are on. Adding a new nav route means: append a tuple to
``NAV_ITEMS`` here; the context processor and the template pick it up
automatically.
"""

from __future__ import annotations

# Header nav rendered in ``base.html`` and ``base_mobile.html``.
# Each tuple is ``(href, label)``. Ordered by ``len(href)`` DESCENDING
# so ``is_active`` picks the longest matching prefix.
NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("/entradas/batch/new", "Lote"),
    ("/casas-acogida", "Casas"),
    ("/acogidas", "Estancias"),
    ("/adopciones", "Adopciones"),
    ("/animales", "Animales"),
    ("/entradas", "Entradas"),
    ("/sanidad", "Actuaciones"),
    ("/voluntarios", "Voluntarios"),
    ("/admin", "Admin"),
)


def resolve_active_nav_href(current_path: str) -> str:
    """Return the longest ``NAV_ITEMS`` href that is a prefix of ``current_path``.

    Match rules (matching the issue #805 test plan):
    - ``current_path == href`` → exact match wins.
    - ``current_path.startswith(href + "/")`` → prefix match. The trailing
      slash prevents ``/entradas`` from matching ``/entradasbatch`` or
      any other path that merely starts with the same string.
    - The home ``"/"`` does NOT match arbitrary paths (otherwise every
      page would render the home as active); it only matches ``"/"`` exactly.

    ``NAV_ITEMS`` is sorted by length descending so the longest match
    wins; no extra tie-break needed.
    """
    for href, _label in NAV_ITEMS:
        if current_path == href:
            return href
        if href != "/" and current_path.startswith(href + "/"):
            return href
    return ""
