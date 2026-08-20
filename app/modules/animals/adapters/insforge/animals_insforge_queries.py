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


__all__ = ["GET_ANIMAL_BY_NCHIP_SQL", "get_animal_by_nchip_sql"]
