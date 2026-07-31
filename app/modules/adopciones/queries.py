"""Pure SQL query builders for the adopciones service seam.

Each builder returns ``(sql, parameters)`` without performing I/O. The service
owns orchestration and mapping while this module owns SQL construction and
parameter shaping per AGENTS.md §22.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Final

from app.core.forms import optional_text, required_text

_required_text = partial(
    required_text, error_template="{field} is required and cannot be empty"
)


ADOPCION_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "animal_id",
    "voluntario_seguimiento_id",
    "fecha_adopcion",
    "fecha_devolucion",
    "donativo_preadopcion",
    "donativo_adopcion",
    "nombre_adoptante",
    "dni_adoptante",
    "telefono_adoptante",
    "email_adoptante",
    "entrada_origen_id",
    "observaciones",
    "tipo_adopcion",
    "responsable_adopcion_id",  # VOL-04 #37: free-text legacy → FK
)

ADOPCION_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    *ADOPCION_WRITE_COLUMNS,
    "fecha_alta",
    "updated_at",
    "activo",
)

_CHECK_ANIMAL_SQL: Final[str] = (
    "SELECT id FROM animales WHERE id = $1 AND activo = true"
)
_CHECK_VOLUNTARIO_SQL: Final[str] = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)
_CHECK_ENTRADA_SQL: Final[str] = "SELECT id FROM entradas WHERE id = $1"

_INSERT_ADOPCION_SQL: Final[str] = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $1 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
checked_entrada AS (
    SELECT id FROM entradas WHERE id = $11
),
checked_responsable AS (
    SELECT id FROM voluntarios WHERE id = $14 AND activo = true
),
inserted AS (
    INSERT INTO adopciones ({", ".join(ADOPCION_WRITE_COLUMNS)})
    SELECT
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
    FROM checked_animal
    WHERE
        ($2::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
        AND ($11::text IS NULL OR EXISTS (SELECT 1 FROM checked_entrada))
        AND ($14::text IS NULL OR EXISTS (SELECT 1 FROM checked_responsable))
    RETURNING {", ".join(ADOPCION_SELECT_COLUMNS)}
)
SELECT {", ".join(ADOPCION_SELECT_COLUMNS)} FROM inserted
"""

_LIST_ADOPCIONES_SQL: Final[str] = (
    f"SELECT {', '.join(ADOPCION_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC "
    "LIMIT 100"
)

_LIST_ADOPCIONES_BY_ADOPTANTE_SQL: Final[str] = (
    f"SELECT {', '.join(ADOPCION_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "AND nombre_adoptante ILIKE '%' || $1 || '%' ESCAPE '\\' "
    "ORDER BY fecha_alta DESC "
    "LIMIT 100"
)

_GET_ADOPCION_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(ADOPCION_SELECT_COLUMNS)} FROM adopciones WHERE id = $1"
)

_UPDATE_ADOPCION_SQL: Final[str] = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $2 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $3 AND activo = true
),
checked_entrada AS (
    SELECT id FROM entradas WHERE id = $12
),
checked_responsable AS (
    SELECT id FROM voluntarios WHERE id = $15 AND activo = true
),
updated AS (
    UPDATE adopciones SET
{", ".join(f"{col} = ${i + 4}" for i, col in enumerate(ADOPCION_WRITE_COLUMNS))},
updated_at = now()
    WHERE id = $1
      AND EXISTS (SELECT 1 FROM checked_animal)
      AND ($3::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
      AND ($12::text IS NULL OR EXISTS (SELECT 1 FROM checked_entrada))
      AND ($15::text IS NULL OR EXISTS (SELECT 1 FROM checked_responsable))
    RETURNING {", ".join(ADOPCION_SELECT_COLUMNS)}
)
SELECT {", ".join(ADOPCION_SELECT_COLUMNS)} FROM updated
"""

_DELETE_ADOPCION_SQL: Final[str] = """
UPDATE adopciones
SET activo = false,
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


def _optional_numeric(params: dict[str, Any], field: str) -> float | None:
    value = params.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number, not a boolean")
    if not isinstance(value, int | float | str):
        raise ValueError(f"{field} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _build_write_params(params: dict[str, Any]) -> list[Any]:
    return [
        _required_text(params, "animal_id"),
        optional_text(params, "voluntario_seguimiento_id"),
        _required_text(params, "fecha_adopcion"),
        optional_text(params, "fecha_devolucion"),
        _optional_numeric(params, "donativo_preadopcion"),
        _optional_numeric(params, "donativo_adopcion"),
        _required_text(params, "nombre_adoptante"),
        optional_text(params, "dni_adoptante"),
        optional_text(params, "telefono_adoptante"),
        optional_text(params, "email_adoptante"),
        optional_text(params, "entrada_origen_id"),
        optional_text(params, "observaciones"),
        optional_text(params, "tipo_adopcion") or "regular",
        optional_text(params, "responsable_adopcion_id"),  # VOL-04 #37
    ]


def build_adopcion_insert(params: dict[str, Any]) -> tuple[str, list[Any]]:
    return _INSERT_ADOPCION_SQL, _build_write_params(params)


def build_adopcion_list() -> tuple[str, list[Any]]:
    return _LIST_ADOPCIONES_SQL, []


def build_adopcion_get_by_id(adopcion_id: str) -> tuple[str, list[Any]]:
    return _GET_ADOPCION_BY_ID_SQL, [adopcion_id]


def build_adopcion_update(
    adopcion_id: str, params: dict[str, Any]
) -> tuple[str, list[Any]]:
    return _UPDATE_ADOPCION_SQL, [adopcion_id, *_build_write_params(params)]


def build_adopcion_delete(adopcion_id: str) -> tuple[str, list[Any]]:
    return _DELETE_ADOPCION_SQL, [adopcion_id]


def build_adopcion_search(nombre_parcial: str) -> tuple[str, list[Any]]:
    return _LIST_ADOPCIONES_BY_ADOPTANTE_SQL, [nombre_parcial]


def build_adopcion_check_animal(animal_id: str) -> tuple[str, list[Any]]:
    return _CHECK_ANIMAL_SQL, [animal_id]


def build_adopcion_check_voluntario(voluntario_id: str) -> tuple[str, list[Any]]:
    return _CHECK_VOLUNTARIO_SQL, [voluntario_id]


def build_adopcion_check_entrada(entrada_id: str) -> tuple[str, list[Any]]:
    return _CHECK_ENTRADA_SQL, [entrada_id]


_CHECK_RESPONSABLE_SQL: Final[str] = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)


def build_adopcion_check_responsable(voluntario_id: str) -> tuple[str, list[Any]]:
    """SELECT for FK check of responsable_adopcion_id (VOL-05 active check)."""
    return _CHECK_RESPONSABLE_SQL, [voluntario_id]
