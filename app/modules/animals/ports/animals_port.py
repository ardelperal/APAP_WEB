"""Hexagonal port for the animals slice (AGENTS.md §31).

Slice #420-7 second method — paginated list, complementing the
read-by-NCHIP path landed in #587. Additional methods
(``create``, ``update``, ``delete``, ``chip_cascade``,
``photo_upload``, ``lifecycle_events``) land as the legacy
:mod:`app.modules.animals.service` migrates.

Adapters MUST translate transport-level errors into the
Protocol-level exceptions declared in :mod:`app.core.data_access`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.animals.domain.animal import Animal


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


__all__ = ["AnimalsPort"]
