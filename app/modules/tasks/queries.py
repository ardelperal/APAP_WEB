"""SQL builder seam for ``app.modules.tasks`` per AGENTS.md section-22.

Query/service separation:
  SQL strings and parameter shaping live here in pure builder functions
  that return ``(sql, params)`` tuples. The service module
  (``service.py``) imports these builders, applies domain validation,
  and talks to the SQL executor.

Rule section-22 - the seam is testable. The shape of the SQL is asserted in
unit tests without spinning up transport, InsForge, or HTTP.

Rule section-4 - column lists and SQL templates live in exactly one place.
All builders here share the same column constants derived from the
schema definition in ``006_create_tarea.sql``.
"""

from __future__ import annotations

import json
from typing import Any, Final

# Columns written by INSERT. Order matches positional params $1..$8.
_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "tipo",
    "origen",
    "prioridad",
    "responsable_id",
    "vencimiento_at",
    "vinculo_tipo",
    "vinculo_id",
    "metadata",
)

# Columns returned by SELECT (used by all query builders).
_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "tipo",
    "origen",
    "prioridad",
    "estado",
    "responsable_id",
    "vencimiento_at",
    "vinculo_tipo",
    "vinculo_id",
    "metadata",
    "created_at",
    "updated_at",
)

# ---- INSERT ---------------------------------------------------------------

_INSERT_TAREA_SQL: Final[str] = """
INSERT INTO tarea (
    tipo, origen, prioridad, responsable_id,
    vencimiento_at, vinculo_tipo, vinculo_id, metadata
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING id, tipo, origen, prioridad, estado, responsable_id,
          vencimiento_at, vinculo_tipo, vinculo_id, metadata,
          created_at, updated_at
"""


def build_insert_tarea(
    *,
    tipo: str,
    origen: str,
    prioridad: str,
    responsable_id: str | None = None,
    vencimiento_at: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, list[Any]]:
    """Build the INSERT for a new tarea.

    Returns ``(sql, params)`` where params has exactly 8 elements
    matching ``_WRITE_COLUMNS``.
    """
    params: list[Any] = [
        tipo,
        origen,
        prioridad,
        responsable_id,
        vencimiento_at,
        vinculo_tipo,
        vinculo_id,
        json.dumps(metadata) if metadata is not None else None,
    ]
    return _INSERT_TAREA_SQL, params


# ---- LIST ----------------------------------------------------------------

_LIST_TAREAS_SQL: Final[str] = """
SELECT id, tipo, origen, prioridad, estado, responsable_id,
       vencimiento_at, vinculo_tipo, vinculo_id, metadata,
       created_at, updated_at
FROM tarea
WHERE ($1::text IS NULL OR estado = $1)
  AND ($2::uuid IS NULL OR responsable_id = $2)
  AND ($3::text IS NULL OR vinculo_tipo = $3)
  AND ($4::uuid IS NULL OR vinculo_id = $4)
ORDER BY
    CASE estado
        WHEN 'urgente'   THEN 1
        WHEN 'pendiente' THEN 2
        WHEN 'en_progreso' THEN 3
        WHEN 'completada'  THEN 4
        WHEN 'cancelada'   THEN 5
        WHEN 'vencida'     THEN 6
        ELSE 7
    END,
    vencimiento_at ASC NULLS LAST,
    created_at DESC
LIMIT $5
OFFSET $6
"""


def build_list_tareas(
    *,
    estado: str | None = None,
    responsable_id: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[str, list[Any]]:
    """Build the list query with optional filters.

    Returns ``(sql, params)`` where params has 6 elements:
    [estado, responsable_id, vinculo_tipo, vinculo_id, limit, offset].
    """
    return _LIST_TAREAS_SQL, [
        estado,
        responsable_id,
        vinculo_tipo,
        vinculo_id,
        limit,
        offset,
    ]


# ---- GET -----------------------------------------------------------------

_GET_TAREA_SQL: Final[str] = """
SELECT id, tipo, origen, prioridad, estado, responsable_id,
       vencimiento_at, vinculo_tipo, vinculo_id, metadata,
       created_at, updated_at
FROM tarea
WHERE id = $1
"""


def build_get_tarea(tarea_id: str) -> tuple[str, list[Any]]:
    """Build the GET-by-id query. Returns ``(sql, params)``."""
    return _GET_TAREA_SQL, [tarea_id]


# ---- UPDATE ESTADO -------------------------------------------------------

_UPDATE_ESTADO_SQL: Final[str] = """
UPDATE tarea
SET estado = $2, updated_at = now()
WHERE id = $1
RETURNING id, tipo, origen, prioridad, estado, responsable_id,
          vencimiento_at, vinculo_tipo, vinculo_id, metadata,
          created_at, updated_at
"""


def build_update_estado(tarea_id: str, nuevo_estado: str) -> tuple[str, list[Any]]:
    """Build the estado-update query. Returns ``(sql, params)``."""
    return _UPDATE_ESTADO_SQL, [tarea_id, nuevo_estado]


# ---- UPDATE RESPONSABLE --------------------------------------------------

_UPDATE_RESPONSABLE_SQL: Final[str] = """
UPDATE tarea
SET responsable_id = $2, updated_at = now()
WHERE id = $1
RETURNING id, tipo, origen, prioridad, estado, responsable_id,
          vencimiento_at, vinculo_tipo, vinculo_id, metadata,
          created_at, updated_at
"""


def build_update_responsable(
    tarea_id: str, responsable_id: str | None
) -> tuple[str, list[Any]]:
    """Build the responsable-update query. Returns ``(sql, params)``."""
    return _UPDATE_RESPONSABLE_SQL, [tarea_id, responsable_id]


# ---- UPDATE METADATA (comentario stored in metadata JSONB) ---------------

_UPDATE_METADATA_SQL: Final[str] = """
UPDATE tarea
SET metadata = jsonb_set(
        COALESCE(metadata, '{}'),
        '{comentario}',
        to_jsonb($2::text)
    ),
    updated_at = now()
WHERE id = $1
RETURNING id, tipo, origen, prioridad, estado, responsable_id,
          vencimiento_at, vinculo_tipo, vinculo_id, metadata,
          created_at, updated_at
"""


def build_update_metadata(
    tarea_id: str, comentario: str | None
) -> tuple[str, list[Any]]:
    """Build the metadata-update query (for closing comentario)."""
    return _UPDATE_METADATA_SQL, [tarea_id, comentario]
