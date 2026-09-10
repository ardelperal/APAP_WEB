"""Write-side SQL builders for the animals LocalBackend adapter.

Extracted from ``animals_local_backend_queries`` to keep both query modules below
the mutation-site ceiling. The domain-owned ``_INSERT_COLUMNS`` tuple remains
the single source of truth for writable column order.
"""

# ruff: noqa: N803 — kwargs intentionally preserve legacy schema column names
from __future__ import annotations

from app.modules.animals.adapters.local_backend.animals_local_backend_queries import (
    _ANIMAL_COLUMNS_SQL,
)
from app.modules.animals.domain.animal import _INSERT_COLUMNS

_DB_COLUMN_BY_DOMAIN_COLUMN = {
    "NCHIP": "nchip",
    "NombreAnimal": "nombreanimal",
    "Especie": "especie",
    "Sexo": "sexo",
    "FNacimiento": "fnacimiento",
    "TraeNChip": "traenchip",
    "FIMPLANTACIONCHIP": "fimplantacionchip",
    "Raza": "raza",
    "Color": "color",
    "Pelo": "pelo",
    "Tamano": "tamano",
    "Caracter": "caracter",
    "FDefuncion": "fdefuncion",
    "Terapia": "terapia",
    "Observaciones": "observaciones",
    "NombreFoto": "nombrefoto",
    "Cartilla": "cartilla",
    "Eutanasia": "eutanasia",
    "RazaPPP": "razappp",
    "Mestizo": "mestizo",
    "EutanasiaOtrasCausas": "eutanasia_otras_causas",
    "EutanasiaEnfermedad": "eutanasia_enfermedad",
    "UltimoEstadoAntesDeFallecido": "ultimo_estado_antes_de_fallecido",
    "ComunicacionARIAC": "comunicacionariac",
}
_INSERT_DB_COLUMNS = ", ".join(
    _DB_COLUMN_BY_DOMAIN_COLUMN[column] for column in _INSERT_COLUMNS
)
_INSERT_BINDS = ", ".join(f"${index}" for index in range(1, len(_INSERT_COLUMNS) + 1))
INSERT_ANIMAL_SQL: str = (
    f"INSERT INTO animales ({_INSERT_DB_COLUMNS}) "  # noqa: S608 — columns are the domain-owned constant; values remain bind parameters
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


def _update_pairs(values: dict[str, str | None]) -> list[tuple[str, str]]:
    """Return supplied update values in the canonical column order."""
    return [
        (column, value)
        for column in UPDATE_ANIMAL_COLUMN_ORDER
        if (value := values.get(column)) is not None
    ]


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
    pairs = _update_pairs(values)
    if not pairs:
        return None
    set_clause = ", ".join(
        f"{_DB_COLUMN_BY_DOMAIN_COLUMN[column]} = ${index + 2}"
        for index, (column, _) in enumerate(pairs)
    )
    sql = (
        "UPDATE animales "  # noqa: S608 — column names come from the domain-owned constant; values remain binds
        f"SET {set_clause} WHERE id = $1 RETURNING {_ANIMAL_COLUMNS_SQL}"
    )
    return sql, [animal_id, *[value for _, value in pairs]]


DELETE_ANIMAL_SQL: str = (
    "UPDATE animales SET activo = FALSE WHERE id = $1 "
    'RETURNING id, nchip AS "NCHIP", nombreanimal AS "NombreAnimal", '
    'especie AS "Especie", sexo AS "Sexo", fnacimiento AS "FNacimiento", activo'
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
