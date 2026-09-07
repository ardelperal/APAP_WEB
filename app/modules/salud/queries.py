"""SQL builder seam for ``app.modules.salud`` per AGENTS.md §22.

HEALTH-04 terapias CRUD (issue #53). The query/service separation:
SQL strings and parameter shaping live here in pure builder functions
that return ``(sql, params)`` tuples. The service module
(``service.py``) imports these builders, applies the per-record
validation pipeline, and talks to the SQL executor.

Rule §22 — the seam is testable. The shape of the SQL is asserted in
``tests/test_salud_queries.py`` without spinning up transport,
LocalBackend, or HTTP. The service layer stays focused on dataclasses,
mapping, validation, and orchestration.

Rule §1 — routes must never import from this module. The graph is
``routes.py -> service.py -> queries.py``; ``routes.py -> queries.py``
would violate the layer boundary.
"""

from __future__ import annotations

from typing import Any, Final

# Columns written by terapia INSERT / UPDATE.
# Order matches the per-record ``params`` dict.
TERAPIA_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "descripcion",
)

# Columns returned by terapia SELECT / INSERT / UPDATE.
TERAPIA_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "animal_id",
    "voluntario_id",
    "fecha",
    "descripcion",
    "created_at",
    "updated_at",
    "activo",
)

# --- Terapia SQL -----------------------------------------------------------

# Atomic INSERT with FK checks (animal exists + activo, voluntario exists +
# activo per VOL-05). TOCTOU-safe: all checks run in the same PostgreSQL
# statement snapshot as the INSERT.
#
# Placeholders:
#   $1  animal_id
#   $2  voluntario_id  (required; must be activo per VOL-05)
#   $3  fecha
#   $4  descripcion
# Atomic INSERT with FK checks (animal exists + activo, voluntario exists +
# activo per VOL-05) plus the lifecycle gate (animal not in
# Incoherente or any Fallecido (*) variant). TOCTOU-safe: all checks
# run in the same PostgreSQL statement snapshot as the INSERT.
#
# Placeholders:
#   $1 — animal_id (UUID)
#   $2 — voluntario_id (UUID)
#   $3 — fecha (YYYY-MM-DD)
#   $4 — descripcion (text, nullable)
#
# Lifecycle gate (issue #46 follow-up):
#   The ``checked_animal`` CTE LEFT JOINs ``animal_current_state`` so a
#   terapia INSERT is short-circuited when the animal is in any of the
#   blocked states: ``Incoherente`` plus the ``Fallecido (*)`` variants.
#   The full set of blocked labels is Albergue, Acogida, Adoptado,
#   Entregado, and Desconocido. The LEFT JOIN keeps healthy animals
#   (no row in ``animal_current_state``
#   yet — their first actuation event has not landed) reachable; the
#   ``IS NULL`` arm of the predicate passes the row through. The
#   ``LIKE 'Fallecido%'`` pattern matches the canonical DB labels
#   declared in ``app/core/domain_lifecycle.py::ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL``
#   so new Fallecido variants added there are picked up automatically
#   (the integration test ``test_core_event_types_set_matches_strenum_members``
#   pins that contract).
_CREATE_TERAPIA_SQL: Final[str] = f"""
WITH checked_animal AS (
    SELECT a.id
    FROM animales a
    LEFT JOIN animal_current_state acs ON a.id = acs.animal_id
    WHERE a.id = $1
      AND a.activo = true
      AND (
          acs.current_state IS NULL
          OR (
              acs.current_state != 'Incoherente'
              AND acs.current_state NOT LIKE 'Fallecido%'
          )
      )
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
inserted AS (
    INSERT INTO terapias ({", ".join(TERAPIA_WRITE_COLUMNS)})
    SELECT $1, $2, $3::date, $4
    FROM checked_animal, checked_voluntario
    WHERE checked_animal.id IS NOT NULL
      AND checked_voluntario.id IS NOT NULL
    RETURNING {", ".join(TERAPIA_SELECT_COLUMNS)}
)
SELECT {", ".join(TERAPIA_SELECT_COLUMNS)} FROM inserted
"""  # noqa: S608 constant identifiers; values are $N binds

# List all active terapias, optionally filtered by animal_id.
# Bounded: LIMIT 100 to prevent table dumps.
_LIST_TERAPIAS_SQL: Final[str] = f"""
SELECT {", ".join(TERAPIA_SELECT_COLUMNS)}
FROM terapias
WHERE activo = true
ORDER BY fecha DESC
LIMIT 100
"""  # noqa: S608 constant identifiers; values are $N binds

_LIST_TERAPIAS_BY_ANIMAL_SQL: Final[str] = f"""
SELECT {", ".join(TERAPIA_SELECT_COLUMNS)}
FROM terapias
WHERE activo = true AND animal_id = $1
ORDER BY fecha DESC
LIMIT 100
"""  # noqa: S608 constant identifiers; values are $N binds

_GET_TERAPIA_BY_ID_SQL: Final[str] = f"""
SELECT {", ".join(TERAPIA_SELECT_COLUMNS)}
FROM terapias WHERE id = $1
"""  # noqa: S608 constant identifiers; values are $N binds

# Atomic UPDATE: same FK + VOL-05 checks as INSERT.
# Placeholders: $1 = terapia_id, $2 = animal_id, $3 = voluntario_id,
# $4 = fecha, $5 = descripcion
_UPDATE_TERAPIA_SQL: Final[str] = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $2 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $3 AND activo = true
),
updated AS (
    UPDATE terapias AS target_terapia SET
        animal_id = $2,
        voluntario_id = $3,
        fecha = $4::date,
        descripcion = $5,
        updated_at = now()
    FROM checked_animal, checked_voluntario
    WHERE target_terapia.id = $1
      AND checked_animal.id IS NOT NULL
      AND checked_voluntario.id IS NOT NULL
    RETURNING target_terapia.id, target_terapia.animal_id, target_terapia.voluntario_id,
             target_terapia.fecha, target_terapia.descripcion,
             target_terapia.created_at, target_terapia.updated_at, target_terapia.activo
)
SELECT {", ".join(TERAPIA_SELECT_COLUMNS)} FROM updated
"""  # noqa: S608 constant identifiers; values are $N binds

# Soft-delete with pre-check: reject if any active recomendaciones exist.
# Returns the terapia id on success; empty result set on failure (either
# terapia doesn't exist, is already deleted, or has pending recommendations).
_DELETE_TERAPIA_SQL: Final[str] = """
WITH pending_recomendaciones AS (
    SELECT id FROM recomendaciones
    WHERE terapia_id = $1 AND activo = true AND completada = false
    LIMIT 1
),
deleted AS (
    UPDATE terapias
    SET activo = false, updated_at = now()
    WHERE id = $1 AND activo = true
      AND NOT EXISTS (SELECT 1 FROM pending_recomendaciones)
    RETURNING id
)
SELECT id FROM deleted
"""

# Check if a terapia exists and is active.
_CHECK_TERAPIA_EXISTS_SQL: Final[str] = (
    "SELECT id FROM terapias WHERE id = $1 AND activo = true"
)

# --- Recomendacion SQL -----------------------------------------------------

RECOMENDACION_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "terapia_id",
    "fecha",
    "texto",
    "completada",
    "created_at",
    "activo",
)

RECOMENDACION_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "terapia_id",
    "fecha",
    "texto",
)

# Atomic INSERT: FK check (terapia exists + activo), then insert.
# Placeholders: $1 = terapia_id, $2 = fecha, $3 = texto
_CREATE_RECOMENDACION_SQL: Final[str] = f"""
WITH checked_terapia AS (
    SELECT id FROM terapias WHERE id = $1 AND activo = true
),
inserted AS (
    INSERT INTO recomendaciones ({", ".join(RECOMENDACION_WRITE_COLUMNS)})
    SELECT $1, $2::date, $3
    FROM checked_terapia
    WHERE checked_terapia.id IS NOT NULL
    RETURNING {", ".join(RECOMENDACION_SELECT_COLUMNS)}
)
SELECT {", ".join(RECOMENDACION_SELECT_COLUMNS)} FROM inserted
"""  # noqa: S608 constant identifiers; values are $N binds

# List active recomendaciones for a terapia.
_LIST_RECOMENDACIONES_BY_TERAPIA_SQL: Final[str] = f"""
SELECT {", ".join(RECOMENDACION_SELECT_COLUMNS)}
FROM recomendaciones
WHERE terapia_id = $1 AND activo = true
ORDER BY fecha DESC
"""  # noqa: S608 constant identifiers; values are $N binds

_GET_RECOMENDACION_BY_ID_SQL: Final[str] = f"""
SELECT {", ".join(RECOMENDACION_SELECT_COLUMNS)}
FROM recomendaciones WHERE id = $1
"""  # noqa: S608 constant identifiers; values are $N binds

# Complete a recomendacion (set completada = true).
# Returns the updated row; fails with 0 rows if the row doesn't exist
# or is already completed (idempotent — completing twice is fine).
_COMPLETE_RECOMENDACION_SQL: Final[str] = f"""
UPDATE recomendaciones
SET completada = true
WHERE id = $1 AND activo = true
RETURNING {", ".join(RECOMENDACION_SELECT_COLUMNS)}
"""  # noqa: S608 constant identifiers; values are $N binds

# Soft-delete a recomendacion.
_DELETE_RECOMENDACION_SQL: Final[str] = """
UPDATE recomendaciones
SET activo = false
WHERE id = $1 AND activo = true
RETURNING id
"""

# --- Builder functions ------------------------------------------------------


def build_create_terapia(
    params: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Pure builder for the atomic terapia INSERT.

    Returns ``(sql, params)`` where params are ordered per
    ``TERAPIA_WRITE_COLUMNS``.
    """
    return _CREATE_TERAPIA_SQL, [
        params["animal_id"],
        params["voluntario_id"],
        params["fecha"],
        params.get("descripcion"),
    ]


def build_list_terapias(
    *,
    animal_id: str | None = None,
) -> tuple[str, list[Any]]:
    """Pure builder for terapia list queries.

    Returns ``(sql, params)`` with ``animal_id`` as the single param
    when filtering; otherwise no params for the global list.
    """
    if animal_id:
        return _LIST_TERAPIAS_BY_ANIMAL_SQL, [animal_id]
    return _LIST_TERAPIAS_SQL, []


def build_get_terapia(terapia_id: str) -> tuple[str, list[Any]]:
    return _GET_TERAPIA_BY_ID_SQL, [terapia_id]


def build_update_terapia(
    terapia_id: str,
    params: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Pure builder for the atomic terapia UPDATE.

    Returns ``(sql, params)`` where params are
    ``[terapia_id, animal_id, voluntario_id, fecha, descripcion]``.
    """
    return _UPDATE_TERAPIA_SQL, [
        terapia_id,
        params["animal_id"],
        params["voluntario_id"],
        params["fecha"],
        params.get("descripcion"),
    ]


def build_delete_terapia(terapia_id: str) -> tuple[str, list[Any]]:
    """Pure builder for soft-delete with pending-recomendaciones check."""
    return _DELETE_TERAPIA_SQL, [terapia_id]


def build_check_terapia_exists(terapia_id: str) -> tuple[str, list[Any]]:
    return _CHECK_TERAPIA_EXISTS_SQL, [terapia_id]


def build_create_recomendacion(
    params: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Pure builder for the atomic recomendacion INSERT.

    Returns ``(sql, params)`` where params are
    ``[terapia_id, fecha, texto]``.
    """
    return _CREATE_RECOMENDACION_SQL, [
        params["terapia_id"],
        params["fecha"],
        params["texto"],
    ]


def build_list_recomendaciones_by_terapia(
    terapia_id: str,
) -> tuple[str, list[Any]]:
    return _LIST_RECOMENDACIONES_BY_TERAPIA_SQL, [terapia_id]


def build_get_recomendacion(
    recomendacion_id: str,
) -> tuple[str, list[Any]]:
    return _GET_RECOMENDACION_BY_ID_SQL, [recomendacion_id]


def build_complete_recomendacion(
    recomendacion_id: str,
) -> tuple[str, list[Any]]:
    return _COMPLETE_RECOMENDACION_SQL, [recomendacion_id]


def build_delete_recomendacion(
    recomendacion_id: str,
) -> tuple[str, list[Any]]:
    return _DELETE_RECOMENDACION_SQL, [recomendacion_id]
