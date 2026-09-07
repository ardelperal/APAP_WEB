"""Use case: list animals, paginated, newest-first by admission date.

Slice #420-7 second surface (complementing ``get_animal_by_nchip``,
landed in #587). The single application-layer entry point for the
hexagonal list path. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
LocalBackend, no Jinja in this file.

Defensive bounds on ``limit`` keep a misconfigured caller from
pulling the whole table: the cap matches the legacy
``list_animales`` handler's MAX_PAGE_SIZE so the hexagonal path is
a drop-in replacement. ``offset`` is clamped to ``>= 0`` to keep the
adapter's ``LIMIT/OFFSET`` clause safe against negative inputs
(postgres rejects them; local_backend-validated postgres inherits the
same behaviour).
"""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal
from app.modules.animals.ports.animals_port import AnimalsPort

MAX_PAGE_SIZE: int = 200


def list_animals(
    animals_port: AnimalsPort,
    *,
    limit: int = 50,
    offset: int = 0,
    activo_only: bool = True,
) -> list[Animal]:
    """Return a paginated slice of animals.

    ``limit`` is clamped to ``[1, MAX_PAGE_SIZE]``; ``offset`` is
    clamped to ``>= 0``. Out-of-range inputs are silently coerced to
    the nearest valid value — the use case is a thin wrapper, not a
    validation gate, and the adapter's SQL is already safe against
    out-of-range values.
    """
    safe_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    safe_offset = max(0, int(offset))
    return animals_port.list_animals(
        limit=safe_limit,
        offset=safe_offset,
        activo_only=activo_only,
    )


__all__ = ["list_animals", "MAX_PAGE_SIZE"]
