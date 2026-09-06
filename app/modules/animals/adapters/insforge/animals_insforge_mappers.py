"""Row-to-domain mappers for the animals InsForge adapter."""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).


from __future__ import annotations

from app.modules.animals.domain.animal import (
    DB_LABEL_TO_ESTADO,
    Animal,
    Especie,
    Sexo,
)
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


def _optional_str(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def _optional_estado(row: dict[str, object]) -> str | None:
    current_state = _optional_str(row, "current_state")
    if current_state is None:
        return None
    return DB_LABEL_TO_ESTADO.get(current_state, "incoherente")


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
        fecha_alta=_optional_str(row, "fecha_alta"),
        estado=_optional_estado(row),
        TraeNChip=_optional_str(row, "TraeNChip"),
        FIMPLANTACIONCHIP=_optional_str(row, "FIMPLANTACIONCHIP"),
        Raza=_optional_str(row, "Raza"),
        Color=_optional_str(row, "Color"),
        Pelo=_optional_str(row, "Pelo"),
        Tamano=_optional_str(row, "Tamano"),
        Caracter=_optional_str(row, "Caracter"),
        FDefuncion=_optional_str(row, "FDefuncion"),
        Terapia=_optional_str(row, "Terapia"),
        Observaciones=_optional_str(row, "Observaciones"),
        NombreFoto=_optional_str(row, "NombreFoto"),
        Cartilla=_optional_str(row, "Cartilla"),
        Eutanasia=_optional_str(row, "Eutanasia"),
        RazaPPP=_optional_str(row, "RazaPPP"),
        Mestizo=_optional_str(row, "Mestizo"),
        EutanasiaOtrasCausas=_optional_str(row, "EutanasiaOtrasCausas"),
        EutanasiaEnfermedad=_optional_str(row, "EutanasiaEnfermedad"),
        UltimoEstadoAntesDeFallecido=_optional_str(
            row, "UltimoEstadoAntesDeFallecido"
        ),
        ComunicacionARIAC=_optional_str(row, "ComunicacionARIAC"),
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
