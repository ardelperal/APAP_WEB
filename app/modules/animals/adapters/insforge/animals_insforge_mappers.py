"""Row-to-domain mappers for the animals InsForge adapter."""

from __future__ import annotations

from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


def _row_to_animal(row: dict[str, object]) -> Animal:
    """Translate a PostgREST row to the hexagonal ``Animal`` entity."""
    return Animal(
        id=str(row["id"]),
        NCHIP=str(row["NCHIP"]),
        NombreAnimal=str(row["NombreAnimal"]),
        Especie=Especie(str(row["Especie"])),
        Sexo=Sexo(str(row["Sexo"])),
        FNacimiento=str(row["FNacimiento"]),
        activo=bool(row["activo"]),
    )


def _row_to_lifecycle_event(
    row: dict[str, object],
) -> AnimalLifecycleEvent:
    """Translate a PostgREST row to ``AnimalLifecycleEvent``."""
    return AnimalLifecycleEvent(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        event_type=LifecycleEventType(str(row["event_type"])),
        event_timestamp=str(row["event_timestamp"]),
        created_by=str(row["created_by"]),
        caused_by_event_id=(
            str(row["caused_by_event_id"])
            if row["caused_by_event_id"] is not None
            else None
        ),
        source_entity_type=(
            str(row["source_entity_type"])
            if row["source_entity_type"] is not None
            else None
        ),
        source_entity_id=(
            str(row["source_entity_id"])
            if row["source_entity_id"] is not None
            else None
        ),
        legacy_source_table=(
            str(row["legacy_source_table"])
            if row["legacy_source_table"] is not None
            else None
        ),
        legacy_source_id=(
            int(row["legacy_source_id"])  # type: ignore[call-overload]
            if row["legacy_source_id"] is not None
            else None
        ),
        metadata=(
            row["metadata"]  # type: ignore[arg-type]
            if row["metadata"] is not None
            else None
        ),
    )


__all__ = ["_row_to_animal", "_row_to_lifecycle_event"]
