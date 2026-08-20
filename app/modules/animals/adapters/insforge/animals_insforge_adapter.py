"""InsForge adapter implementing :class:`AnimalsPort` for ``animales``.

The only place in the slice that talks to the InsForge transport
(via :class:`~app.core.data_access.SqlExecutor`). SQL lives in
:mod:`app.modules.animals.adapters.insforge.animals_insforge_queries`
(AGENTS.md §22); this module is pure orchestration. Thin and
stateless; the DI provider in :mod:`app.modules.animals.di.animals_di`
constructs one per request from the already-pooled
:class:`~app.core.insforge.InsForgeClient`.
"""
from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    get_animal_by_nchip_sql,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.ports.animals_port import AnimalsPort


class AnimalsInsforgeAdapter(AnimalsPort):
    """InsForge-backed implementation of the animals port."""

    def __init__(self, client: SqlExecutor) -> None:
        self._client = client

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        sql, params = get_animal_by_nchip_sql(nchip)
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])


def _row_to_animal(row: dict[str, object]) -> Animal:
    """Translate a PostgREST row dict to the hexagonal ``Animal`` entity.

    ``Especie`` and ``Sexo`` come back as strings from the wire; the
    ``StrEnum`` constructor rejects unknown values, matching the
    legacy ``service._row_to_animal`` (the column set is constrained
    to the two enums at the DB level so unknown values would be a
    data-integrity bug, not a runtime event).
    """
    return Animal(
        id=str(row["id"]),
        NCHIP=str(row["NCHIP"]),
        NombreAnimal=str(row["NombreAnimal"]),
        Especie=Especie(str(row["Especie"])),
        Sexo=Sexo(str(row["Sexo"])),
        FNacimiento=str(row["FNacimiento"]),
        activo=bool(row["activo"]),
    )


__all__ = ["AnimalsInsforgeAdapter"]