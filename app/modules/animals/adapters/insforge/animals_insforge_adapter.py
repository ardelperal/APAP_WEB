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
    create_animal_sql,
    get_animal_by_nchip_sql,
    list_animals_sql,
    update_animal_sql,
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

    def list_animals(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[Animal]:
        sql, params = list_animals_sql(
            limit=limit,
            offset=offset,
            activo_only=activo_only,
        )
        rows = self._client.execute_sql(sql, params)
        return [_row_to_animal(row) for row in rows]

    def create_animal(
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
    ) -> Animal:
        sql, params = create_animal_sql(
            nchip=nchip,
            nombre=nombre,
            especie=especie.value,
            sexo=sexo.value,
            fnacimiento=fnacimiento,
        )
        rows = self._client.execute_sql(sql, params)
        # ``INSERT ... RETURNING`` always yields one row on success;
        # the empty-list branch is a defensive guard for an
        # unexpected transport shape (would surface as an opaque
        # ``IndexError`` otherwise, which is harder to diagnose).
        if not rows:
            raise RuntimeError(  # noqa: TRY003 — operator-facing diagnostic
                "INSERT INTO animales RETURNING produced no rows — "
                "the transport shape has drifted, expected exactly "
                "one row"
            )
        return _row_to_animal(rows[0])

    def update_animal(
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
    ) -> Animal | None:
        # ``None``-skip on the SQL side is delegated to the helper;
        # if every field is ``None`` the helper returns ``None`` and
        # we short-circuit before touching the transport (the
        # partial UPDATE would be a no-op anyway, and the route
        # handler should not pay for a round-trip).
        sql_params = update_animal_sql(
            animal_id=animal_id,
            nombre=nombre,
            especie=None if especie is None else especie.value,
            sexo=None if sexo is None else sexo.value,
            fnacimiento=fnacimiento,
        )
        if sql_params is None:
            # All kwargs were ``None``: surface the no-op by reading
            # the row back via the same primary-key lookup the legacy
            # code uses (would happen via get_animal, but importing
            # the helper into itself is awkward — re-query is cheap).
            return self.get_animal_by_id(animal_id)
        sql, params = sql_params
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def get_animal_by_id(self, animal_id: str) -> Animal | None:
        """Read-only helper used by ``update_animal``'s no-op branch.

        Not part of the public ``AnimalsPort`` surface — it's a
        private adapter implementation detail (the no-op branch
        could equivalently return a sentinel, but reading the row
        back keeps the contract symmetric with the legacy
        ``update_animal`` which also returns the row unchanged).
        """
        rows = self._client.execute_sql(
            "SELECT id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
            "\"FNacimiento\", activo FROM animales WHERE id = $1",
            [animal_id],
        )
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
