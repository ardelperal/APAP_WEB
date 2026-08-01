"""Service layer for HEALTH-05 terapias + recomendaciones (issue #54).

Provides CRUD operations for ``terapias`` (therapy sessions) and their
associated ``recomendaciones`` (follow-up notes).

Tables:

- ``terapias``: id, animal_id, fecha, voluntario_id, descripcion,
  created_at, updated_at, activo.
- ``recomendaciones``: id, terapia_id, fecha, texto, completada,
  created_at, activo.

Validation contracts (per spec HEALTH-05):

- ``voluntario_id`` MUST exist AND be active (VOL-05 rule).
  Checked atomically inside the terapia INSERT/UPDATE CTE.
- A ``terapia`` with pending recommendations
  (``completada=false``) CANNOT be soft-deleted (409 Conflict).
  The service checks this BEFORE the soft-delete statement.
- ``ON DELETE CASCADE`` is enforced at DB level for
  ``recomendaciones.terapia_id``.

Audit logging via ``log_safe`` per AGENTS.md §9.

Framework-agnostic: routes are thin HTTP glue; SQL, validation,
mapping, and orchestration all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.forms import optional_text as _optional_text
from app.core.forms import required_text as _required_text
from app.core.logging import log_safe

# --- Terapia dataclass ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Terapia:
    """A public row representation for ``terapias``."""

    id: str
    animal_id: str
    fecha: str
    activo: bool = True
    voluntario_id: str | None = None
    descripcion: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class Recomendacion:
    """A public row representation for ``recomendaciones``."""

    id: str
    terapia_id: str
    fecha: str
    texto: str
    activo: bool = True
    completada: bool = False
    created_at: str | None = None


# --- Column contracts ------------------------------------------------------


_TERAPIA_COLUMNS: tuple[str, ...] = (
    "id",
    "animal_id",
    "fecha",
    "voluntario_id",
    "descripcion",
    "created_at",
    "updated_at",
    "activo",
)

_TERAPIA_WRITE_COLUMNS: tuple[str, ...] = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "descripcion",
)

_RECOMENDACION_COLUMNS: tuple[str, ...] = (
    "id",
    "terapia_id",
    "fecha",
    "texto",
    "completada",
    "created_at",
    "activo",
)


# --- SQL (private) --------------------------------------------------------


_CHECK_ANIMAL_SQL: str = (
    "SELECT id FROM animales WHERE id = $1 AND activo = true"
)

_CHECK_VOLUNTARIO_ACTIVO_SQL: str = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)

_INSERT_TERAPIA_SQL: str = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $1 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
inserted AS (
    INSERT INTO terapias ({", ".join(_TERAPIA_WRITE_COLUMNS)})
    SELECT $1, $2, $3::date, $4
    FROM checked_animal, checked_voluntario
    WHERE checked_animal.id IS NOT NULL
      AND checked_voluntario.id IS NOT NULL
    RETURNING {", ".join(_TERAPIA_COLUMNS)}
)
SELECT {", ".join(_TERAPIA_COLUMNS)} FROM inserted
"""

_LIST_TERAPIAS_SQL: str = (
    f"SELECT {', '.join(_TERAPIA_COLUMNS)} "
    "FROM terapias WHERE activo = true "
    "ORDER BY fecha DESC "
    "LIMIT 100"
)

_LIST_TERAPIAS_BY_ANIMAL_SQL: str = (
    f"SELECT {', '.join(_TERAPIA_COLUMNS)} "
    "FROM terapias WHERE activo = true AND animal_id = $1 "
    "ORDER BY fecha DESC "
    "LIMIT 100"
)

_GET_TERAPIA_BY_ID_SQL: str = (
    f"SELECT {', '.join(_TERAPIA_COLUMNS)} "
    "FROM terapias WHERE id = $1"
)

_UPDATE_TERAPIA_SQL: str = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $1 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
updated AS (
    UPDATE terapias AS t SET
        animal_id = $1,
        voluntario_id = $2,
        fecha = $3::date,
        descripcion = $4,
        updated_at = now()
    FROM checked_animal, checked_voluntario
    WHERE t.id = $5
      AND checked_animal.id IS NOT NULL
      AND checked_voluntario.id IS NOT NULL
    RETURNING {", ".join(_TERAPIA_COLUMNS)}
)
SELECT {", ".join(_TERAPIA_COLUMNS)} FROM updated
"""

_SOFT_DELETE_TERAPIA_SQL: str = """
UPDATE terapias
SET activo = false,
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""

_CHECK_PENDING_RECOMENDACIONES_SQL: str = (
    "SELECT id FROM recomendaciones "
    "WHERE terapia_id = $1 AND activo = true AND completada = false "
    "LIMIT 1"
)

_INSERT_RECOMENDACION_SQL: str = f"""
WITH checked_terapia AS (
    SELECT id FROM terapias WHERE id = $1 AND activo = true
),
inserted AS (
    INSERT INTO recomendaciones (terapia_id, fecha, texto)
    SELECT $1, $2::date, $3
    FROM checked_terapia
    WHERE checked_terapia.id IS NOT NULL
    RETURNING {", ".join(_RECOMENDACION_COLUMNS)}
)
SELECT {", ".join(_RECOMENDACION_COLUMNS)} FROM inserted
"""

_LIST_RECOMENDACIONES_BY_TERAPIA_SQL: str = (
    f"SELECT {', '.join(_RECOMENDACION_COLUMNS)} "
    "FROM recomendaciones "
    "WHERE terapia_id = $1 AND activo = true "
    "ORDER BY fecha ASC"
)

_GET_RECOMENDACION_BY_ID_SQL: str = (
    f"SELECT {', '.join(_RECOMENDACION_COLUMNS)} "
    "FROM recomendaciones WHERE id = $1"
)

_UPDATE_RECOMENDACION_COMPLETADA_SQL: str = """
UPDATE recomendaciones
SET completada = true
WHERE id = $1 AND activo = true
RETURNING id
"""

_SOFT_DELETE_RECOMENDACION_SQL: str = """
UPDATE recomendaciones
SET activo = false
WHERE id = $1 AND activo = true
RETURNING id
"""


# --- Row mappers ----------------------------------------------------------


def _row_to_terapia(row: dict[str, Any]) -> Terapia:
    return Terapia(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        fecha=str(row["fecha"]),
        voluntario_id=(
            str(row["voluntario_id"])
            if row.get("voluntario_id")
            else None
        ),
        descripcion=row.get("descripcion"),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _row_to_recomendacion(row: dict[str, Any]) -> Recomendacion:
    return Recomendacion(
        id=str(row["id"]),
        terapia_id=str(row["terapia_id"]),
        fecha=str(row["fecha"]),
        texto=row.get("texto") or "",
        completada=bool(row.get("completada", False)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        activo=bool(row.get("activo", True)),
    )


# --- public API ----------------------------------------------------------


def create_terapia(
    client: SqlExecutor,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Terapia:
    """Insert a new ``terapia`` row.

    Validates:
    - ``animal_id`` exists and is active (via CTE JOIN).
    - ``voluntario_id`` exists and is active — VOL-05 rule
      (via CTE JOIN).

    On 0 rows returned, raises ``ValueError`` with a specific
    message indicating which FK check failed.
    """
    animal_id = _required_text(params, "animal_id")
    voluntario_id = _required_text(params, "voluntario_id")
    fecha = _required_text(params, "fecha")
    descripcion = _optional_text(params, "descripcion")

    # Validate date format (YYYY-MM-DD)
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise ValueError("fecha must have format YYYY-MM-DD") from None

    rows = client.execute_sql(
        _INSERT_TERAPIA_SQL,
        [animal_id, voluntario_id, fecha, descripcion],
    )
    if not rows:
        # Disambiguate: which FK failed?
        animal_rows = client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id])
        if not animal_rows:
            raise ValueError(
                f"animal_id must reference an active animal (not found: {animal_id})"
            )
        if not animal_rows[0].get("activo", False):
            raise ValueError(
                f"animal_id must reference an active animal (inactive: {animal_id})"
            )
        vol_rows = client.execute_sql(
            _CHECK_VOLUNTARIO_ACTIVO_SQL, [voluntario_id]
        )
        if not vol_rows:
            raise ValueError(
                f"voluntario_id must reference an active volunteer "
                f"(not found or inactive: {voluntario_id})"
            )
        raise ValueError(
            "Terapia creation failed (animal or voluntario validation error)"
        )

    terapia = _row_to_terapia(rows[0])
    log_safe(
        "therapy.created",
        terapia_id=terapia.id,
        animal_id=terapia.animal_id,
        actor_user_id=actor_user_id,
    )
    return terapia


def list_terapias(
    client: SqlExecutor,
    *,
    animal_id: str | None = None,
) -> list[Terapia]:
    """List active ``terapias`` rows.

    When ``animal_id`` is provided, returns only rows for that animal.
    Otherwise returns the global list (LIMIT 100), ordered by fecha DESC.
    """
    if animal_id and animal_id.strip():
        rows = client.execute_sql(
            _LIST_TERAPIAS_BY_ANIMAL_SQL, [animal_id.strip()]
        )
    else:
        rows = client.execute_sql(_LIST_TERAPIAS_SQL)
    return [_row_to_terapia(row) for row in rows]


def get_terapia(
    client: SqlExecutor, terapia_id: str
) -> Terapia | None:
    """Return one ``terapia`` by id, or ``None`` if not found."""
    rows = client.execute_sql(_GET_TERAPIA_BY_ID_SQL, [terapia_id])
    return _row_to_terapia(rows[0]) if rows else None


def update_terapia(
    client: SqlExecutor,
    terapia_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Terapia | None:
    """Update an existing ``terapia`` row.

    Same FK checks as ``create_terapia`` (animal activo, voluntario
    activo). Returns ``None`` when the id does not exist.
    Raises ``ValueError`` when a FK check fails.
    """
    animal_id = _required_text(params, "animal_id")
    voluntario_id = _required_text(params, "voluntario_id")
    fecha = _required_text(params, "fecha")
    descripcion = _optional_text(params, "descripcion")

    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise ValueError("fecha must have format YYYY-MM-DD") from None

    rows = client.execute_sql(
        _UPDATE_TERAPIA_SQL,
        [animal_id, voluntario_id, fecha, descripcion, terapia_id],
    )
    if not rows:
        # Check if terapia exists
        if get_terapia(client, terapia_id) is None:
            return None
        # FK check failed — disambiguate
        animal_rows = client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id])
        if not animal_rows:
            raise ValueError(
                f"animal_id must reference an active animal (not found: {animal_id})"
            )
        vol_rows = client.execute_sql(
            _CHECK_VOLUNTARIO_ACTIVO_SQL, [voluntario_id]
        )
        if not vol_rows:
            raise ValueError(
                f"voluntario_id must reference an active volunteer "
                f"(not found or inactive: {voluntario_id})"
            )
        raise ValueError(
            "Terapia update failed (animal or voluntario validation error)"
        )

    terapia = _row_to_terapia(rows[0])
    log_safe(
        "therapy.updated",
        terapia_id=terapia.id,
        animal_id=terapia.animal_id,
        actor_user_id=actor_user_id,
    )
    return terapia


class TerapiaDeleteError(ValueError):
    """Raised when a terapia cannot be deleted due to pending recomendaciones."""

    pass


def delete_terapia(
    client: SqlExecutor,
    terapia_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Soft-delete a ``terapia`` row.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the id does not exist or was already inactive.

    Raises ``TerapiaDeleteError`` when the terapia has any active
    (``activo=true``) recommendation with ``completada=false``.
    The delete is NOT performed in this case (409 Conflict contract).
    """
    # First check: does the terapia exist and is active?
    terapia = get_terapia(client, terapia_id)
    if terapia is None or not terapia.activo:
        return False

    # Check for pending recomendaciones
    pending = client.execute_sql(
        _CHECK_PENDING_RECOMENDACIONES_SQL, [terapia_id]
    )
    if pending:
        raise TerapiaDeleteError(
            "No se puede borrar la terapia: tiene recomendaciones pendientes "
            "(marca todas las recomendaciones como completadas antes de borrar)"
        )

    rows = client.execute_sql(_SOFT_DELETE_TERAPIA_SQL, [terapia_id])
    deleted = bool(rows)
    if deleted:
        log_safe(
            "therapy.deleted",
            terapia_id=terapia_id,
            actor_user_id=actor_user_id,
        )
    return deleted


def create_recomendacion(
    client: SqlExecutor,
    terapia_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Recomendacion:
    """Insert a new ``recomendacion`` linked to a ``terapia``.

    Validates that ``terapia_id`` references an active terapia
    (via CTE JOIN). Raises ``ValueError`` when the terapia does not
    exist or is inactive.
    """
    fecha = _required_text(params, "fecha")
    texto = _required_text(params, "texto")

    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise ValueError("fecha must have format YYYY-MM-DD") from None

    rows = client.execute_sql(
        _INSERT_RECOMENDACION_SQL,
        [terapia_id, fecha, texto],
    )
    if not rows:
        # Check if terapia exists and is active
        terapia_rows = client.execute_sql(
            _GET_TERAPIA_BY_ID_SQL, [terapia_id]
        )
        if not terapia_rows:
            raise ValueError(
                f"terapia_id must reference an active terapia (not found: {terapia_id})"
            )
        if not terapia_rows[0].get("activo", False):
            raise ValueError(
                f"terapia_id must reference an active terapia (inactive: {terapia_id})"
            )
        raise ValueError(
            "Recomendacion creation failed (terapia validation error)"
        )

    recomendacion = _row_to_recomendacion(rows[0])
    log_safe(
        "recomendacion.created",
        recomendacion_id=recomendacion.id,
        terapia_id=recomendacion.terapia_id,
        actor_user_id=actor_user_id,
    )
    return recomendacion


def list_recomendaciones(
    client: SqlExecutor,
    terapia_id: str,
) -> list[Recomendacion]:
    """List active ``recomendaciones`` for a ``terapia``."""
    rows = client.execute_sql(
        _LIST_RECOMENDACIONES_BY_TERAPIA_SQL, [terapia_id]
    )
    return [_row_to_recomendacion(row) for row in rows]


def complete_recomendacion(
    client: SqlExecutor,
    recomendacion_id: str,
    *,
    actor_user_id: str | None = None,
) -> Recomendacion | None:
    """Mark a ``recomendacion`` as completed.

    Returns the updated ``Recomendacion`` on success, or ``None`` if
    the id does not exist or was already inactive.
    """
    rows = client.execute_sql(
        _UPDATE_RECOMENDACION_COMPLETADA_SQL, [recomendacion_id]
    )
    if not rows:
        # Check if exists
        existing = client.execute_sql(
            _GET_RECOMENDACION_BY_ID_SQL, [recomendacion_id]
        )
        if not existing:
            return None
        if not existing[0].get("activo", False):
            return None
        raise ValueError(
            "complete_recomendacion failed unexpectedly"
        )

    full_rows = client.execute_sql(
        _GET_RECOMENDACION_BY_ID_SQL, [recomendacion_id]
    )
    recomendacion = _row_to_recomendacion(full_rows[0])
    log_safe(
        "recomendacion.completed",
        recomendacion_id=recomendacion.id,
        terapia_id=recomendacion.terapia_id,
        actor_user_id=actor_user_id,
    )
    return recomendacion


def delete_recomendacion(
    client: SqlExecutor,
    recomendacion_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Soft-delete a ``recomendacion`` row.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the id does not exist or was already inactive.
    """
    rows = client.execute_sql(
        _SOFT_DELETE_RECOMENDACION_SQL, [recomendacion_id]
    )
    deleted = bool(rows)
    if deleted:
        log_safe(
            "recomendacion.deleted",
            recomendacion_id=recomendacion_id,
            actor_user_id=actor_user_id,
        )
    return deleted


def get_recomendacion_terapia_id(
    client: SqlExecutor,
    recomendacion_id: str,
) -> str | None:
    """Return the ``terapia_id`` for a ``recomendacion``, or ``None`` if not found."""
    rows = client.execute_sql(
        "SELECT terapia_id FROM recomendaciones WHERE id = $1",
        [recomendacion_id],
    )
    if not rows:
        return None
    return str(rows[0].get("terapia_id", ""))

