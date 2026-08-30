"""SQL for the voluntarios slice (AGENTS.md §22: SQL in exactly one place).

Column names match the bootstrap schema in ``app/core/domain_voluntarios.py``
(lowercase: ``voluntario``, ``tel1``, ``email``, ``dni``).

The adapter translates between the lowercase DB column names and the
hexagonal ``Voluntario`` dataclass fields.
"""
from __future__ import annotations

#: Full read shape for ``list_voluntarios`` and ``get_voluntario_by_id``.
_VOLUNTARIOS_COLUMNS_SQL = (
    'id, voluntario, tel1, tel2, email, dni, '
    "fecha_alta, updated_at, activo"
)

LIST_VOLUNTARIOS_SQL: str = f"""
SELECT {_VOLUNTARIOS_COLUMNS_SQL}
FROM voluntarios
WHERE activo = true
ORDER BY voluntario ASC
"""  # noqa: S608 constant identifiers; no user input

GET_VOLUNTARIO_BY_ID_SQL: str = f"""
SELECT {_VOLUNTARIOS_COLUMNS_SQL}
FROM voluntarios
WHERE id = $1
"""  # noqa: S608 constant identifiers; $1 is a UUID bind

LIST_VOLUNTARIO_ROLES_SQL: str = """
SELECT tipo_rol
FROM roles_voluntario
WHERE voluntario_id = $1
ORDER BY tipo_rol ASC
"""  # noqa: S608 constant identifiers; $1 is a UUID bind

__all__ = [
    "LIST_VOLUNTARIOS_SQL",
    "GET_VOLUNTARIO_BY_ID_SQL",
    "LIST_VOLUNTARIO_ROLES_SQL",
]
