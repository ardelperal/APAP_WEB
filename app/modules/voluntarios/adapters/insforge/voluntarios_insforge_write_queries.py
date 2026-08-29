"""Write (INSERT / UPDATE) SQL for the voluntarios slice.

Column names match the bootstrap schema in ``app/core/domain_voluntarios.py``
(lowercase: ``voluntario``, ``tel1``, ``email``, ``dni``).
"""
from __future__ import annotations

#: INSERT columns (writeable subset of the full row).
_INSERT_COLUMNS = (
    "voluntario",
    "tel1",
    "tel2",
    "email",
    "dni",
)

_CREATE_VOLUNTARIO_SQL: str = f"""
INSERT INTO voluntarios ({", ".join(_INSERT_COLUMNS)})
VALUES ($1, $2, $3, $4, $5)
RETURNING id, voluntario, tel1, tel2, email, dni,
         fecha_alta, updated_at, activo
"""  # noqa: S608 constant identifiers; $N are positional binds

#: Atomic deactivate: the ``activo = true`` guard is evaluated INSIDE the
#: UPDATE under PostgreSQL's row lock, eliminating the TOCTOU window of a
#: separate SELECT + UPDATE pattern.
_DEACTIVATE_VOLUNTARIO_SQL: str = """
UPDATE voluntarios
SET activo = false, updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""  # noqa: S608 constant identifiers; $1 is a UUID bind

#: Assign a role: inserts into the junction table.
#: Raises PostgreSQL unique violation (23505) if the role is already assigned.
ASSIGN_ROLE_SQL: str = """
INSERT INTO roles_voluntario (voluntario_id, tipo_rol)
VALUES ($1, $2)
RETURNING id, voluntario_id, tipo_rol, created_at
"""  # noqa: S608 constant identifiers; $N are positional binds

#: Remove a role: deletes from the junction table.
#: Idempotent: if the row does not exist, DELETE returns 0 rows — no error.
REMOVE_ROLE_SQL: str = """
DELETE FROM roles_voluntario
WHERE voluntario_id = $1 AND tipo_rol = $2
RETURNING id
"""  # noqa: S608 constant identifiers; $N are positional binds

__all__ = [
    "_INSERT_COLUMNS",
    "CREATE_VOLUNTARIO_SQL",
    "DEACTIVATE_VOLUNTARIO_SQL",
    "ASSIGN_ROLE_SQL",
    "REMOVE_ROLE_SQL",
]

#: Alias matching the module-level naming convention.
DEACTIVATE_VOLUNTARIO_SQL = _DEACTIVATE_VOLUNTARIO_SQL
CREATE_VOLUNTARIO_SQL = _CREATE_VOLUNTARIO_SQL
