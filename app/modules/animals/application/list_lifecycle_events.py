"""Use case: read the chronological lifecycle timeline of one animal.

Slice #420-7 seventh surface (joins get_animal_by_nchip #587,
list_animals #596, create_animal #597, update_animal #603,
delete_animal #604 and record_lifecycle_event #609). The single
application-layer entry point for hexagonal lifecycle-event reads.
Delegates to :class:`~app.modules.animals.ports.AnimalsPort` so
the application code stays transport-agnostic (AGENTS.md §31) — no
FastAPI, no LocalBackend, no Jinja in this file.

The use case enforces the only pre-flight invariant the legacy
``service.list_lifecycle_events`` did:

- ``animal_id`` is mandatory and must be non-blank.

``event_types`` (optional filter) is forwarded unchanged — the
adapter translates the enum list to a SQL ``event_type = ANY(...)``
clause. ``limit`` is clamped to ``[1, MAX_PAGE_SIZE=200]`` so a
misconfigured caller can't pull the whole timeline; ``offset`` is
clamped to ``>= 0`` to keep the SQL ``OFFSET`` clause safe.
"""
from __future__ import annotations

from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)
from app.modules.animals.ports.animals_port import AnimalsPort

MAX_PAGE_SIZE: int = 200


class LifecycleListValidationError(ValueError):
    """Raised when ``animal_id`` fails the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _require_animal_id(animal_id: str | None) -> str:
    if animal_id is None:
        raise LifecycleListValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio"
        )
    stripped = animal_id.strip()
    if not stripped:
        raise LifecycleListValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio y no puede estar vacio"
        )
    return stripped


def list_lifecycle_events(
    animals_port: AnimalsPort,
    animal_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    event_types: list[LifecycleEventType] | None = None,
) -> list[AnimalLifecycleEvent]:
    """Return the chronological timeline of ``animal_id``'s events.

    Returns ``[]`` when the animal has no events or when the
    ``event_types`` filter matches nothing. ``limit`` is clamped to
    ``[1, MAX_PAGE_SIZE]``; ``offset`` to ``>= 0``.
    """
    clean_animal_id = _require_animal_id(animal_id)
    safe_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    safe_offset = max(0, int(offset))

    return animals_port.list_lifecycle_events(
        animal_id=clean_animal_id,
        limit=safe_limit,
        offset=safe_offset,
        event_types=event_types,
    )


__all__ = [
    "list_lifecycle_events",
    "LifecycleListValidationError",
    "MAX_PAGE_SIZE",
]
