"""Hexagonal port for the animals slice (AGENTS.md §31).

PR-B of epic #420 routes create, update, and delete through this port.
The writable kwargs mirror the 24-column ``AnimalForm`` contract; ``id``,
``estado``, ``activo``, and ``fecha_alta`` remain system-owned.

Adapters MUST translate transport-level errors into the
Protocol-level exceptions declared in :mod:`app.core.data_access`.
"""
# ruff: noqa: N803 — kwargs intentionally preserve legacy schema column names
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.modules.animals.domain.animal import (
    Animal,
    AnimalSearchResult,
    Especie,
    Sexo,
)
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)
from app.modules.animals.ports.photo_asset import PhotoAsset


@runtime_checkable
class AnimalsPort(Protocol):
    """Backend-agnostic interface for the animals slice."""

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        """Return the animal with this NCHIP, or ``None`` if not found.

        NCHIP is the business primary key per
        ``docs/discovery/feature-01-animal-lifecycle.md`` §"Central
        identity: microchip".
        """

    def get_animal_by_id(self, animal_id: str) -> Animal | None:
        """Return the animal with this UUID primary key, or ``None``.

        Distinct from :meth:`get_animal_by_nchip`: this looks up by the
        database primary key. ``animal_id`` is mandatory and non-blank
        (validated in the use case).
        """

    def search_animals(
        self,
        *,
        q: str | None = None,
        chip: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        estado: str | None = None,
        fecha_alta_since: str | None = None,
        fecha_alta_until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnimalSearchResult:
        """Search animals with optional filters.

        Returns a fresh count over the same WHERE clause plus the requested
        data page. The application use case clamps ``limit`` and ``offset``.
        """

    def list_animals(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[Animal]:
        """Return animals newest-first by fecha_alta, then NCHIP.

        ``limit`` is the maximum number of rows the caller is willing
        to receive; adapters are free to return fewer but must not
        exceed it. ``offset`` skips that many rows from the head of the
        ordering (use the previous response's length to walk a full
        list — there is no opaque cursor yet because the slice is
        still small enough that off-by-one is cheap).

        ``activo_only=True`` preserves the retired list route's active-only
        filter; pass ``False`` for the
        historical-record paths that need to see inactive rows.
        """

    def create_animal(  # noqa: N803, PLR0913  # schema-named fields mirror the 24-column AnimalForm contract
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
        TraeNChip: str | None = None,
        FIMPLANTACIONCHIP: str | None = None,
        Raza: str | None = None,
        Color: str | None = None,
        Pelo: str | None = None,
        Tamano: str | None = None,
        Caracter: str | None = None,
        FDefuncion: str | None = None,
        Terapia: str | None = None,
        Observaciones: str | None = None,
        NombreFoto: str | None = None,
        Cartilla: str | None = None,
        Eutanasia: str | None = None,
        RazaPPP: str | None = None,
        Mestizo: str | None = None,
        EutanasiaOtrasCausas: str | None = None,
        EutanasiaEnfermedad: str | None = None,
        UltimoEstadoAntesDeFallecido: str | None = None,
        ComunicacionARIAC: str | None = None,
    ) -> Animal:
        """Insert a new animal and return the persisted row.

        The 24 writable fields have parity with ``AnimalForm`` and the
        corresponding fields on the 28-field hexagonal entity. The adapter is
        responsible for the primary-key generation
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

    def update_animal(  # noqa: N803, PLR0913  # schema-named fields mirror AnimalForm except saga-owned NCHIP
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
        TraeNChip: str | None = None,
        FIMPLANTACIONCHIP: str | None = None,
        Raza: str | None = None,
        Color: str | None = None,
        Pelo: str | None = None,
        Tamano: str | None = None,
        Caracter: str | None = None,
        FDefuncion: str | None = None,
        Terapia: str | None = None,
        Observaciones: str | None = None,
        NombreFoto: str | None = None,
        Cartilla: str | None = None,
        Eutanasia: str | None = None,
        RazaPPP: str | None = None,
        Mestizo: str | None = None,
        EutanasiaOtrasCausas: str | None = None,
        EutanasiaEnfermedad: str | None = None,
        UltimoEstadoAntesDeFallecido: str | None = None,
        ComunicacionARIAC: str | None = None,
    ) -> Animal | None:
        """Update the named fields of the animal with ``animal_id``.

        The mutable fields have parity with the writable subset of the
        28-field hexagonal entity. NCHIP changes remain exclusive to the chip
        saga. Each kwarg is ``None``-skipped — a partial update writes only
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

    def change_animal_chip(
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
        """Saga: change the animal's NCHIP and propagate across 6 tables.

        Tables touched (atomic, rolled back together on any failure):

        - ``animals`` (the ``NCHIP`` column itself)
        - ``entradas``, ``acogidas``, ``adopciones``,
          ``actuaciones_sanitarias``, ``terapias`` (the 5 dependent
          tables that carry the legacy ``chip`` column)
        - ``animal_lifecycle_events`` (an append of the
          ``CHIP_CHANGED`` event with the legacy ``metadata`` JSON
          carrying ``{old_chip, new_chip, reason}``)

        The adapter runs the saga in a single transaction. Pre-flight
        validations (non-empty ``new_chip``/``reason``; ``new_chip``
        not equal to ``old_chip``; uniqueness of ``new_chip``; current
        chip matches ``old_chip``) happen BEFORE the transaction
        opens. On any failure inside the transaction the adapter
        rolls back and returns ``success=False`` with the error
        message — the route handler translates that into the
        appropriate HTTP code (422 for validation, 409 for unique
        violations, 500 for unexpected transport failures).

        Returns a :class:`ChangeChipResult` with the per-table row
        counts so the operator can audit the blast radius without
        re-querying.
        """

    def resolve_animal_photo(
        self, animal_id: str
    ) -> PhotoAsset | None:
        """Resolve an owned photo asset stream (issue #285).

        Returns ``None`` when the animal does not exist. Returns a
        :class:`PhotoAsset` otherwise; ``is_placeholder`` distinguishes
        a real storage object from the fallback asset.

        The asset carries intrinsic media type and known byte length only.
        HTTP cache policy and validators belong to the future delivery
        adapter, not this port. The consumer owns ``stream`` and MUST call
        ``close()`` after complete, partial, failed, or cancelled consumption.

        ``animal_id`` is mandatory and non-blank (validated in the
        use case).
        """


__all__ = ["AnimalSearchResult", "AnimalsPort"]
