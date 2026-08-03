"""SQL builder seam for ``app.modules.sanidad`` per AGENTS.md §22.

HEALTH-02 batch endpoint (issue #51). The query/service separation:
SQL strings and parameter shaping live here in pure builder functions
that return ``(sql, params)`` tuples. The service module
(``batch_service.py``) imports these builders, applies the per-record
validation pipeline, and talks to the SQL executor.

Rule §22 — the seam is testable. The shape of the SQL is asserted in
``tests/test_sanidad_queries.py`` without spinning up transport,
InsForge, or HTTP. The service layer stays focused on dataclasses,
mapping, validation, and orchestration.

Rule §1 — routes must never import from this module. The graph is
``routes.py -> service.py -> queries.py``; ``routes.py -> queries.py``
would violate the layer boundary.

Rule §4 — column lists and SQL templates live in exactly one place.
The batch endpoint shares the column contract with the single-record
INSERT defined in ``service.py`` (``_WRITE_COLUMNS``,
``_SELECT_COLUMNS``); re-deriving them here would break the rule.

Atomicity (CRITICAL):
    The CTE is one PostgreSQL statement. Every FK check, the D-24
    fecha_alta rule, and the INSERT run under the same statement
    snapshot. ``bool_and(is_valid)`` gates the INSERT through
    ``WHERE all_valid.ok = true`` so a single bad row short-circuits
    the entire write — partial batches are structurally impossible.

    The single-record service (``create_actuacion_sanitaria``) uses
    the same atomic-CTE pattern; the batch builder generalises it
    across ``unnest()`` arrays. See ``service.py`` for the
    single-record commentary.

D-24 inheritance:
    The batch endpoint inherits the D-24 fecha validation rule
    (reglas 1+2+3) from HEALTH-01 / #50. The reason vocabulary
    in the ``validation_per_record`` CASE mirrors the disambiguation
    messages ``sanidad/service.py`` surfaces for single-record
    failures, so the operator-facing error copy is uniform across
    single-record and batch endpoints.
"""

from __future__ import annotations

from typing import Any, Final

# Columns the batch INSERT writes. Order matches the per-record
# ``params`` dict and the CTE's ``unnest`` tuple. Mirrored from
# ``sanidad/service.py::_WRITE_COLUMNS`` — single source of truth per §4.
BATCH_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "tipo_actuacion_id",
    "veterinario",
    "observaciones",
    "material_utilizado",
)


# Columns the CTE returns per row. ``kind`` distinguishes the result
# row's origin (``inserted`` vs ``validation_error``); the service uses
# it to walk the response and split successes from failures.
_BATCH_RESULT_KIND: Final[str] = "kind"
_BATCH_RESULT_INDEX: Final[str] = "batch_index"
_BATCH_RESULT_REASON: Final[str] = "reason"


# Single CTE that fans records through ``unnest`` (parallel arrays, one
# per column), joins against the three FK tables, validates each row,
# and atomically inserts the valid ones into ``actuacion_sanitaria``.
#
# Param map (positional):
#   $1  animal_id[]            UUIDs of target animals
#   $2  voluntario_id[]        optional, may contain NULLs
#   $3  fecha[]                ISO dates
#   $4  tipo_actuacion_id[]    optional
#   $5  veterinario[]          free text
#   $6  observaciones[]        free text
#   $7  material_utilizado[]   free text
#   $8  dry_run                boolean flag; TRUE = preview only
#
# The INSERT filter `dry_run = false` is what makes the staging preview
# truly side-effect-free: setting ``dry_run=true`` short-circuits the
# INSERT (the main query references ``inserted`` only to walk its
# rows; when the CTE inserts nothing, the main query returns zero
# ``kind='inserted'`` rows but still emits the
# ``kind='validation_error'`` rows for the per-record reason copy).
_BATCH_INSERT_SQL: Final[str] = """
WITH input_data AS (
    SELECT
        animal_id,
        voluntario_id,
        fecha::date AS fecha,
        tipo_actuacion_id,
        veterinario,
        observaciones,
        material_utilizado,
        ROW_NUMBER() OVER () - 1 AS batch_index
    FROM unnest(
        $1::text[], $2::text[], $3::date[],
        $4::text[], $5::text[], $6::text[], $7::text[]
    ) AS t(
        animal_id, voluntario_id, fecha,
        tipo_actuacion_id, veterinario, observaciones, material_utilizado
    )
),
checked_animals AS (
    SELECT a.id, a.fecha_alta
    FROM animales a
    -- The arrays come in as ``$N::text[]`` (see the ``unnest`` block
    -- above), so ``i.animal_id`` is text. ``animales.id`` is UUID; cast
    -- before joining or Postgres raises ``operator does not exist:
    -- uuid = text``.
    JOIN input_data i ON a.id = i.animal_id::uuid
    WHERE a.activo = true
),
checked_voluntarios AS (
    SELECT v.id
    FROM voluntarios v
    JOIN input_data i ON v.id = i.voluntario_id::uuid
    WHERE v.activo = true
),
checked_tipos AS (
    SELECT c.id
    FROM catalogos_pruebas c
    JOIN input_data i ON c.id = i.tipo_actuacion_id::uuid
),
validated AS (
    SELECT
        i.animal_id,
        i.voluntario_id,
        i.fecha,
        i.tipo_actuacion_id,
        i.veterinario,
        i.observaciones,
        i.material_utilizado,
        i.batch_index,
        (ca.id IS NOT NULL
            AND (ca.fecha_alta IS NULL OR ca.fecha_alta::date <= i.fecha)
            AND (i.voluntario_id IS NULL OR cv.id IS NOT NULL)
            AND (i.tipo_actuacion_id IS NULL OR ct.id IS NOT NULL)
        ) AS is_valid,
        CASE
            WHEN ca.id IS NULL THEN 'animal_no_activo'
            WHEN ca.fecha_alta IS NOT NULL AND ca.fecha_alta::date > i.fecha
                THEN 'fecha_anterior_alta'
            WHEN i.voluntario_id IS NOT NULL AND cv.id IS NULL
                THEN 'voluntario_inactivo'
            WHEN i.tipo_actuacion_id IS NOT NULL AND ct.id IS NULL
                THEN 'tipo_prueba_inexistente'
            ELSE NULL
        END AS reason
    FROM input_data i
    LEFT JOIN checked_animals ca ON ca.id = i.animal_id::uuid
    LEFT JOIN checked_voluntarios cv ON cv.id = i.voluntario_id::uuid
    LEFT JOIN checked_tipos ct ON ct.id = i.tipo_actuacion_id::uuid
),
all_valid AS (
    SELECT COALESCE(bool_and(is_valid), TRUE) AS ok
    FROM validated
),
inserted AS (
    INSERT INTO actuacion_sanitaria (
        animal_id, voluntario_id, fecha, tipo_actuacion_id,
        veterinario, observaciones, material_utilizado
    )
    SELECT
        v.animal_id::uuid, v.voluntario_id::uuid, v.fecha, v.tipo_actuacion_id::uuid,
        v.veterinario, v.observaciones, v.material_utilizado
    FROM validated v
    CROSS JOIN all_valid
    WHERE all_valid.ok
      AND v.is_valid
      AND $8::boolean = FALSE
    RETURNING
        id, animal_id, voluntario_id, fecha, tipo_actuacion_id,
        veterinario, observaciones, material_utilizado,
        fecha_alta, updated_at, activo
),
inserted_with_index AS (
    SELECT
        'inserted'::text AS kind,
        ROW_NUMBER() OVER () - 1 AS batch_index,
        NULL::text AS reason,
        id, animal_id, voluntario_id, fecha, tipo_actuacion_id,
        veterinario, observaciones, material_utilizado,
        fecha_alta, updated_at, activo
    FROM inserted
)
SELECT
    kind,
    batch_index,
    reason,
    id, animal_id, voluntario_id, fecha, tipo_actuacion_id,
    veterinario, observaciones, material_utilizado,
    fecha_alta, updated_at, activo
FROM inserted_with_index
UNION ALL
SELECT
    'validation_error'::text AS kind,
    batch_index,
    reason,
    NULL::text AS id, animal_id, voluntario_id, fecha,
    NULL::text AS tipo_actuacion_id,
    NULL::text AS veterinario, NULL::text AS observaciones,
    NULL::text AS material_utilizado,
    NULL::timestamp AS fecha_alta,
    NULL::timestamp AS updated_at,
    NULL::boolean AS activo
FROM validated
WHERE NOT is_valid
ORDER BY kind, batch_index
"""


def build_batch_insert(
    records: list[dict[str, Any]], *, dry_run: bool
) -> tuple[str, list[Any]]:
    """Pure builder for the atomic batch INSERT.

    Returns ``(sql, params)`` where ``params`` is a list of 8 positional
    values: 7 column-arrays (one per ``BATCH_WRITE_COLUMNS``, each of
    length ``len(records)``) followed by the ``dry_run`` boolean.

    The builder enforces the empty-batch contract at the SEAM, so a
    caller cannot accidentally send an empty ``unnest()`` (which would
    return zero rows and silently produce an "all-good, but no inserts"
    response — a misleading staging preview).

    Raises
    ------
    ValueError
        When ``records`` is empty (the route layer also 422s on this,
        but the builder refuses for defense in depth).
    TypeError
        When ``records`` contains anything other than a ``dict``
        (e.g. a positional tuple) so the column unpacking is
        unambiguous.
    """
    if not records:
        raise ValueError(
            "batch must contain at least one record (build_batch_insert called "
            "with an empty list)"
        )
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TypeError(
                f"batch record at index {index} must be a dict, "
                f"got {type(record).__name__}"
            )

    arrays: list[list[Any]] = []
    for column in BATCH_WRITE_COLUMNS:
        arrays.append([record.get(column) for record in records])

    params: list[Any] = [*arrays, bool(dry_run)]
    return _BATCH_INSERT_SQL, params


# --- HEALTH-03 resumen (issue #52) -----------------------------------------
# Get the latest actuacion_sanitaria per tipo (catalogos_pruebas.observaciones)
# for a given animal.  One row per tipo, ordered by fecha DESC, capped at the
# most-recent row per tipo via DISTINCT ON.
#
# Param: $1 — animal_id (UUID text)
_BUILD_RESUMEN_SANITARIO_SQL: str = """
SELECT DISTINCT ON (cp.observaciones)
    a.animal_id               AS animal_id,
    cp.observaciones          AS tipo,
    a.fecha                   AS ultima_fecha,
    a.observaciones           AS ultimo_resultado,
    cp.codigo                 AS ultima_descripcion,
    a.material_utilizado      AS producto
FROM actuacion_sanitaria a
JOIN catalogos_pruebas cp ON cp.id = a.tipo_actuacion_id
WHERE a.activo = true
  AND a.animal_id = $1
ORDER BY cp.observaciones, a.fecha DESC
"""


def build_resumen_sanitario(animal_id: str) -> tuple[str, list[Any]]:
    """Pure builder for the resumen sanitario per-type latest-actuacion query.

    Returns ``(sql, params)`` where params is ``[animal_id]``.

    The query uses ``DISTINCT ON (cp.observaciones)`` to return exactly one
    row per ``catalogos_pruebas.observaciones`` (the tipo grouping), ordered
    by ``fecha DESC`` so the retained row is the most recent actuation of
    that type.
    """
    return _BUILD_RESUMEN_SANITARIO_SQL, [animal_id]


_GET_ANIMAL_NCHIP_SQL: str = """
SELECT nchip FROM animales WHERE id = $1 AND activo = true
"""


def build_get_animal_nchip(animal_id: str) -> tuple[str, list[Any]]:
    """Return the nchip for an active animal, or None if not found."""
    return _GET_ANIMAL_NCHIP_SQL, [animal_id]
