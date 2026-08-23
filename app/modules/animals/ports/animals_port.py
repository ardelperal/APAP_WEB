"""Hexagonal port for the animals slice (AGENTS.md §31).

Slice #420-7 seventh method — ``list_lifecycle_events`` joins
``get_animal_by_nchip`` (#587), ``list_animals`` (#596),
``create_animal`` (#597), ``update_animal`` (#603),
``delete_animal`` (#604) and ``record_lifecycle_event`` (#609).
Additional methods (``chip_cascade``, ``photo_upload``) land as
separate slices.

The port carries the round-trip fields the hexagonal
:class:`Animal` dataclass already encodes (NCHIP, NombreAnimal,
Especie, Sexo, FNacimiento). Legacy ``TbFichaAnimal`` columns
``TraeNChip``, ``FIMPLANTACIONCHIP``, ``Raza``, ``Color``, ``Pelo``,
``Tamano``, ``Caracter`` are not in the dataclass yet — they land as
a separate slice once we decide whether to widen the entity or
carry a parallel ``AnimalCreateRequest`` so the legacy
``dict[str, Any]`` shape can keep its full surface.

Adapters MUST translate transport-level errors into the
Protocol-level exceptions declared in :mod:`app.core.data_access`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


@runtime_checkable
class AnimalsPort(Protocol):
    """Backend-agnostic interface for the animals slice."""

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        """Return the animal with this NCHIP, or ``None`` if not found.

        NCHIP is the business primary key per
        ``docs/discovery/feature-01-animal-lifecycle.md`` §"Central
        identity: microchip".
        """

    def list_animals(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[Animal]:
        """Return a paginated slice of animals, oldest-first by NCHIP.

        ``limit`` is the maximum number of rows the caller is willing
        to receive; adapters are free to return fewer but must not
        exceed it. ``offset`` skips that many rows from the head of the
        ordering (use the previous response's length to walk a full
        list — there is no opaque cursor yet because the slice is
        still small enough that off-by-one is cheap).

        ``activo_only=True`` mirrors the legacy filter on
        :func:`app.modules.animals.service.list_animales` so the
        hexagonal path is a drop-in replacement for the legacy
        ``list_animales`` route handler; pass ``False`` for the
        historical-record paths that need to see inactive rows.
        """

    def create_animal(
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
    ) -> Animal:
        """Insert a new animal and return the persisted row.

        The adapter is responsible for the primary-key generation
        (``id`` comes back via ``INSERT ... RETURNING id``) and for
        any transport-specific uniqueness check on ``NCHIP``. The
        returned :class:`Animal` reflects the row as stored, including
        ``id`` and ``activo=True``.

        Adapters MUST raise :class:`app.core.data_access.UniqueViolation`
        (or a subclass) when the NCHIP already exists so the
        application layer can translate it into a 409 — the legacy
        ``create_animal`` propagates ``InsForgeError`` for the same
        condition, and the hexagonal path uses the data-access layer's
        Protocol-level exception so callers stay transport-free.
        """

    def update_animal(
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
    ) -> Animal | None:
        """Update the named fields of the animal with ``animal_id``.

        Each kwarg is ``None``-skipped — a partial update writes only
        the fields the caller passed. Passing every kwarg as ``None``
        is a no-op that returns the current row (a future slice could
        reject this as a validation error; for now the legacy
        ``service.update_animal`` returns the row unchanged).

        Returns the updated :class:`Animal`, or ``None`` when the id
        does not exist (``UPDATE ... RETURNING`` with zero rows). The
        adapter is responsible for translating transport errors
        (e.g. invalid enum) into the data-access layer's Protocol
        exceptions so callers stay transport-free.
        """

    def delete_animal(self, animal_id: str) -> Animal | None:
        """Soft-delete the animal with ``animal_id`` (sets ``activo=False``).

        Idempotent: a second call on an already-inactive animal
        returns the same row (the ``SET activo = FALSE`` is a no-op).
        Returns the deactivated :class:`Animal` (``activo=False``)
        so the route handler can confirm the state transition, or
        ``None`` when ``animal_id`` does not exist.

        Hard-deletes (row removal) are out of scope here — the
        legacy ``TbFichaAnimal`` rows stay in the table for audit
        even after the animal leaves the live list (issue #431,
        Finding 3).
        """

    def record_lifecycle_event(
        self,
        *,
        animal_id: str,
        event_type: LifecycleEventType,
        event_timestamp: str | datetime,
        created_by: str,
        caused_by_event_id: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        legacy_source_table: str | None = None,
        legacy_source_id: int | None = None,
        metadata: dict | None = None,
    ) -> AnimalLifecycleEvent:
        """Append one event to ``animal_lifecycle_events``.

        Idempotent via ``ON CONFLICT (animal_id, event_type,
        event_timestamp) DO NOTHING``: a retry of the same logical
        event collapses to a single row (the table's natural-key
        UNIQUE constraint is what makes the ``ON CONFLICT`` clause
        resolve to a no-op).

        Returns the persisted :class:`AnimalLifecycleEvent` (the
        adapter fills ``id`` and ``created_at`` from
        ``INSERT ... RETURNING``). The caller can also use the return
        value to confirm the ``ON CONFLICT`` path: when the row
        already existed the adapter returns the existing event, not a
        new one — the caller does not have to re-query.
        """

    def list_lifecycle_events(
        self,
        animal_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_types: list[LifecycleEventType] | None = None,
    ) -> list[AnimalLifecycleEvent]:
        """Return the chronological timeline of ``animal_id``'s events.

        ``event_timestamp ASC`` ordering produces the legacy timeline
        shape — newest at the bottom, oldest at the top — that the
        ``/animales/{id}`` detail view renders. ``event_types`` filters
        the timeline to a subset of ``LifecycleEventType`` (used by
        the ``state resolver`` UI per D-23 to render only the events
        that drive the current state).

        ``limit`` defaults to 50 and ``offset`` defaults to 0; the
        caller walks the timeline by stepping ``offset += len(result)``
        until ``len(result) < limit``. There is no opaque cursor yet
        because the per-animal timeline is bounded by the animal's
        lifespan (a few dozen events even for a long-lived foster
        chain).

        Returns ``[]`` when the animal has no events, or when the
        optional ``event_types`` filter matches nothing. ``animal_id``
        is mandatory and non-blank (validated in the use case).
        """


__all__ = ["AnimalsPort"]
