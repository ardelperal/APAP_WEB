"""Hexagonal port for the animals slice (AGENTS.md §31).

This is the first surface — only the read-by-NCHIP path. Additional
methods (``list_animals``, ``create``, ``update``, ``delete``,
``chip_cascade``, ``photo_upload``, ``lifecycle_events``) land as
the legacy :mod:`app.modules.animals.service` migrates.

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


__all__ = ["AnimalsPort"]