"""Hexagonal port for the animals slice (AGENTS.md §31).

Slice #420-7 third method — ``create_animal`` joins ``get_animal_by_nchip``
(#587) and ``list_animals`` (#596). Additional methods (``update``,
``delete``, ``chip_cascade``, ``photo_upload``, ``lifecycle_events``)
land as the legacy :mod:`app.modules.animals.service` migrates.

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

from typing import Protocol, runtime_checkable

from app.modules.animals.domain.animal import Animal, Especie, Sexo


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


__all__ = ["AnimalsPort"]
