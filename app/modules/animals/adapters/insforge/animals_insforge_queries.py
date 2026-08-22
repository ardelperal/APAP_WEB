"""SQL for the animals slice (AGENTS.md §22: SQL in exactly one place).

Selects only the columns the hexagonal :class:`Animal` dataclass
needs. ``FNacimiento`` comes back as ISO 8601 string from
InsForge's PostgREST adapter.
"""
from __future__ import annotations

GET_ANIMAL_BY_NCHIP_SQL: str = (
    "SELECT id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo "
    "FROM animales "
    'WHERE "NCHIP" = $1 AND activo = TRUE '
    "LIMIT 1"
)


def get_animal_by_nchip_sql(nchip: str) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the NCHIP lookup.

    Public entry point so the application layer can assert on the
    SQL shape without spinning up the transport (rule §22). The
    adapter delegates here so the SQL is defined once.
    """
    return GET_ANIMAL_BY_NCHIP_SQL, [nchip]


# ``list_animals`` — paginated read, oldest-first by NCHIP. The legacy
# ``list_animales`` route uses the same ordering (issue #587
# reconciliation note). ``activo = TRUE`` matches the default filter
# in the application-layer wrapper; the adapter accepts an explicit
# override so the historical-record path can opt out.
LIST_ANIMALS_SQL: str = (
    "SELECT id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo "
    "FROM animales "
    "{where_clause}"
    'ORDER BY "NCHIP" ASC '
    "LIMIT $1 OFFSET $2"
)


def list_animals_sql(
    *,
    limit: int,
    offset: int,
    activo_only: bool,
) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the paginated list.

    Public entry point so the application layer can assert on the
    SQL shape without spinning up the transport (rule §22). The
    adapter delegates here so the SQL is defined once.

    Parameters are passed through verbatim — the application layer
    is responsible for clamping ``limit`` and ``offset`` to safe
    ranges; this helper does no defensive bounds-checking because
    it is the only caller that should be exercised in tests, and
    we want the surface to fail loudly on bad inputs.

    ``limit`` and ``offset`` are coerced to ``str`` because the
    InsForge client serialises bind parameters as strings on the
    wire; the integer values land in postgres via the same implicit
    text→int8 cast the legacy ``service.py`` already relies on.
    """
    where_clause = "WHERE activo = TRUE " if activo_only else ""
    return (
        LIST_ANIMALS_SQL.format(where_clause=where_clause),
        [str(limit), str(offset)],
    )


# ``create_animal`` — INSERT ... RETURNING so the adapter gets the
# generated ``id`` in one round-trip. The column list is the
# hexagonal minimum (5 fields the ``Animal`` dataclass round-trips);
# legacy ``TbFichaAnimal`` columns (Raza, Color, ...) land in a
# follow-up slice once the dataclass widens or a parallel
# ``AnimalCreateRequest`` lands. ``activo`` defaults to TRUE at the
# column level (NOT NULL DEFAULT TRUE) so the INSERT omits it; the
# ``RETURNING`` clause projects it back so the returned ``Animal``
# carries the effective value.
INSERT_ANIMAL_SQL: str = (
    "INSERT INTO animales "
    '("NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento") '
    "VALUES ($1, $2, $3, $4, $5) "
    "RETURNING id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
    "\"FNacimiento\", activo"
)


def create_animal_sql(
    *,
    nchip: str,
    nombre: str,
    especie: str,
    sexo: str,
    fnacimiento: str,
) -> tuple[str, list[str]]:
    """Return the ``(sql, params)`` tuple for the INSERT.

    ``especie`` and ``sexo`` are accepted as ``str`` because the
    hexagonal :class:`Especie` / :class:`Sexo` enums are ``StrEnum``,
    so the value IS the string the SQL wants — no extra coercion.
    """
    return (
        INSERT_ANIMAL_SQL,
        [nchip, nombre, especie, sexo, fnacimiento],
    )


__all__ = [
    "GET_ANIMAL_BY_NCHIP_SQL",
    "LIST_ANIMALS_SQL",
    "INSERT_ANIMAL_SQL",
    "create_animal_sql",
    "get_animal_by_nchip_sql",
    "list_animals_sql",
]
