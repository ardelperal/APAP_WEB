"""Write-side SQL builders for the animals InsForge adapter.

Extracted from ``animals_insforge_queries`` to keep both query modules below
the mutation-site ceiling. The domain-owned ``_INSERT_COLUMNS`` tuple remains
the single source of truth for writable column order.
"""
# ruff: noqa: N803 — kwargs intentionally preserve legacy schema column names
from __future__ import annotations

from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    _ANIMAL_COLUMNS_SQL,
)
from app.modules.animals.domain.animal import _INSERT_COLUMNS

_QUOTED_INSERT_COLUMNS = ", ".join(f'"{column}"' for column in _INSERT_COLUMNS)
_INSERT_BINDS = ", ".join(f"${index}" for index in range(1, len(_INSERT_COLUMNS) + 1))
INSERT_ANIMAL_SQL: str = (
    f"INSERT INTO animales ({_QUOTED_INSERT_COLUMNS}) "  # noqa: S608 — columns are the domain-owned constant; values remain bind parameters
    f"VALUES ({_INSERT_BINDS}) RETURNING {_ANIMAL_COLUMNS_SQL}"
)


def create_animal_sql(
    *,
    nchip: str,
    nombre: str,
    especie: str,
    sexo: str,
    fnacimiento: str,
    **optional_fields: str | None,
) -> tuple[str, list[str | None]]:
    """Return SQL and ordered binds for all 24 writable fields."""
    values = {
        "NCHIP": nchip,
        "NombreAnimal": nombre,
        "Especie": especie,
        "Sexo": sexo,
        "FNacimiento": fnacimiento,
        **optional_fields,
    }
    return INSERT_ANIMAL_SQL, [values.get(column) for column in _INSERT_COLUMNS]


UPDATE_ANIMAL_COLUMN_ORDER: tuple[str, ...] = _INSERT_COLUMNS[1:]


def update_animal_sql(
    *,
    animal_id: str,
    nombre: str | None,
    especie: str | None,
    sexo: str | None,
    fnacimiento: str | None,
    **optional_fields: str | None,
) -> tuple[str, list[str]] | None:
    """Return SQL and binds for a partial update, or ``None`` for a no-op."""
    values = {
        "NombreAnimal": nombre, "Especie": especie, "Sexo": sexo,
        "FNacimiento": fnacimiento,
        **optional_fields,
    }
    pairs = [
        (column, value)
        for column in UPDATE_ANIMAL_COLUMN_ORDER
        if (value := values.get(column)) is not None
    ]
    if not pairs:
        return None
    set_clause = ", ".join(f'"{column}" = ${index + 2}' for index, (column, _) in enumerate(pairs))
    sql = (
        "UPDATE animales "  # noqa: S608 — column names come from the domain-owned constant; values remain binds
        f"SET {set_clause} WHERE id = $1 RETURNING {_ANIMAL_COLUMNS_SQL}"
    )
    return sql, [animal_id, *[value for _, value in pairs]]


DELETE_ANIMAL_SQL: str = (
    "UPDATE animales SET activo = FALSE WHERE id = $1 "
    "RETURNING id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo"
)


def delete_animal_sql(animal_id: str) -> tuple[str, list[str]]:
    """Return SQL and binds for the soft-delete."""
    return DELETE_ANIMAL_SQL, [animal_id]


__all__ = [
    "DELETE_ANIMAL_SQL",
    "INSERT_ANIMAL_SQL",
    "UPDATE_ANIMAL_COLUMN_ORDER",
    "create_animal_sql",
    "delete_animal_sql",
    "update_animal_sql",
]
