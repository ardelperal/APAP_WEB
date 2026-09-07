"""Service layer for HEALTH-01 sanidad (CRUD).

Owns SQL, validation, FK checks, mapping, and soft-delete for the
``actuacion_sanitaria`` table (legacy ``TbActuacionSanitaria`` mirror).
The ``tipo_actuacion_id`` column is a FK to ``catalogos_pruebas``
(CATALOG-01 #65) — D-HEALTH-01. The ``fecha`` column is validated per
the **D-24 rule** (formally defined in this slice; see ``docs/decisiones-
proyecto.md``): the date must be ISO-formatted, not in the future, and
not before the animal's ``fecha_alta`` (with a NULL-exemption for legacy
animals that lack ``fecha_alta``).

Validation contract:

- Required: ``animal_id``, ``fecha`` (the only mandatory fields).
- ``animal_id`` MUST reference an active ``animales`` row (FK check in
  the CTE — D-HEALTH-05).
- ``voluntario_id`` is optional. When provided, it MUST reference an
  active ``voluntarios`` row (VOL-05, D-HEALTH-05). Soft-deletes aside.
- ``tipo_actuacion_id`` is optional. The FK is validated by the DB; the
  service does NOT pre-check the catalog (an invalid id surfaces as
  ``BackendError`` from the CTE, which the route translates to 422).
- D-24 reglas 1+2 (format + future-date): checked by the pure helper
  ``_validate_fecha_d24`` before any DB call.
- D-24 regla 3 (fecha anterior a animales.fecha_alta): checked atomically
  inside the CTE's ``checked_animal`` filter.
- Soft-delete via ``activo = false`` + ``updated_at = now()``; physical
  deletes are forbidden (project-wide pattern).
- ``search_actuaciones_by_animal`` is keyed by ``animal_id`` (UUID) — no
  ILIKE needed; ordered by ``fecha DESC`` with hard ``LIMIT 100``.

CRITICAL-1 (TOCTOU-safe writes): create / update run validation + write
in a single CTE so PostgreSQL's statement-level snapshot eliminates the
window between the FK SELECTs and the INSERT / UPDATE. On 0 rows
returned, the service runs targeted disambiguation SELECTs to raise a
specific ``ValueError`` for the operator (the success path is atomic —
the failure-path disambiguation reads are operator-UX only).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.core.catalogs import (
    list_catalogos_periodicidad as _list_catalogos_periodicidad,
)
from app.core.catalogs import (
    list_catalogos_pruebas as _list_catalogos_pruebas,
)
from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.sanidad import queries
from app.modules.sanidad.scheduling import schedule_periodic_task


def _post_create_schedule(client: SqlExecutor, actuacion: ActuacionSanitaria) -> None:
    """Run after create_actuacion_sanitaria commits: schedule next periodic task.

    HEALTH-05 (#54). Extracted to a named function so tests can monkeypatch it
    without patching the module-level import.
    """
    try:
        schedule_periodic_task(client, actuacion, _list_catalogos_periodicidad(client))
    except Exception:
        pass  # non-fatal


@dataclass(frozen=True, slots=True)
class ActuacionSanitaria:
    """A public service-row representation for ``actuacion_sanitaria``."""

    id: str
    animal_id: str
    fecha: str
    activo: bool = True
    tipo_actuacion_id: str | None = None
    veterinario: str | None = None
    observaciones: str | None = None
    voluntario_id: str | None = None
    material_utilizado: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


_WRITE_COLUMNS: tuple[str, ...] = (
    "animal_id",
    "voluntario_id",
    "fecha",
    "tipo_actuacion_id",
    "veterinario",
    "observaciones",
    "material_utilizado",
)


_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
    "animal_id",
    "voluntario_id",
    "fecha",
    "tipo_actuacion_id",
    "veterinario",
    "observaciones",
    "material_utilizado",
    "fecha_alta",
    "updated_at",
    "activo",
)


_UPDATE_RETURNING_COLUMNS: tuple[str, ...] = tuple(
    f"target_actuacion.{column}" for column in _SELECT_COLUMNS
)


# --- FK validation queries (defense in depth over the DB FK constraints) ---
# These run inside the CTE (see _INSERT_ACTUACION_SANITARIA_SQL /
# _UPDATE_ACTUACION_SANITARIA_SQL below) so PostgreSQL evaluates them
# under a single statement snapshot. They are also re-used by
# ``_raise_validation_error`` for the disambiguation path AFTER the CTE
# returns 0 rows.
_CHECK_ANIMAL_SQL: str = (
    "SELECT id FROM animales WHERE id = $1 AND activo = true"
)


_CHECK_VOLUNTARIO_SQL: str = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)


_CHECK_TIPO_ACTUACION_SQL: str = (
    "SELECT id FROM catalogos_pruebas WHERE id = $1"
)


# --- Atomic write SQL (CRITICAL-1: validation + write in one CTE) ---------
# PostgreSQL evaluates every CTE under the same statement snapshot, so the
# INSERT (or UPDATE) sees the same view of animales / voluntarios /
# catalogos_pruebas as the FK checks. There is no window between the
# SELECT and the write for a concurrent admin to deactivate a row.
#
# D-24 regla 3 (fecha anterior a animales.fecha_alta) is folded into the
# CTE via ``checked_animal`` — the filter ``(fecha_alta IS NULL OR fecha_alta::date <= $3::date)``
# means: if the animal has no ``fecha_alta`` (legacy animals imported
# without the metadato), the lower bound is skipped; otherwise the
# actuation date must be on or after the animal's intake date.
#
# Placeholders:
#   $1  animal_id          (required FK)
#   $2  voluntario_id      (optional FK; NULL when not provided)
#   $3  fecha              (DATE, required; D-24 validated before this CTE)
#   $4  tipo_actuacion_id  (optional FK to catalogos_pruebas)
#   $5  veterinario
#   $6  observaciones
#   $7  material_utilizado
_INSERT_ACTUACION_SANITARIA_SQL: str = f"""
WITH checked_animal AS (
    SELECT id, fecha_alta FROM animales WHERE id = $1 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
checked_tipo AS (
    SELECT id FROM catalogos_pruebas WHERE id = $4
),
inserted AS (
    INSERT INTO actuacion_sanitaria ({", ".join(_WRITE_COLUMNS)})
    SELECT
        $1, $2, $3::date, $4, $5, $6, $7
    FROM checked_animal
    WHERE
        (checked_animal.fecha_alta IS NULL OR checked_animal.fecha_alta::date <= $3::date)
        AND ($2::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
        AND ($4::text IS NULL OR EXISTS (SELECT 1 FROM checked_tipo))
    RETURNING {", ".join(_SELECT_COLUMNS)}
)
SELECT {", ".join(_SELECT_COLUMNS)} FROM inserted
"""  # noqa: S608 constant identifiers; values are $N binds


# CRITICAL-2 + P2-2 (risk review 2026-07-04, mirroring adopciones):
# bounded result set so a malicious or runaway caller cannot dump the
# whole table.
_LIST_ACTUACIONES_SANITARIAS_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "  # noqa: S608 constant identifiers; values are $N binds
    "FROM actuacion_sanitaria "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC "
    "LIMIT 100"
)


# D-HEALTH-04: ``search_actuaciones_by_animal`` keys by ``animal_id`` (UUID).
# Ordered by ``fecha DESC`` (most-recent clinical event first) and capped
# at ``LIMIT 100`` to avoid DOSing the table.
_LIST_BY_ANIMAL_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "  # noqa: S608 constant identifiers; values are $N binds
    "FROM actuacion_sanitaria "
    "WHERE activo = true AND animal_id = $1 "
    "ORDER BY fecha DESC, fecha_alta DESC "
    "LIMIT 100"
)


_GET_ACTUACION_BY_ID_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "  # noqa: S608 constant identifiers; values are $N binds
    "FROM actuacion_sanitaria WHERE id = $1"
)


# Atomic update: FK checks + D-24 regla 3 + UPDATE in one CTE (mirrors
# the INSERT CTE). The id is $1; the FK placeholders shift by one relative
# to the INSERT CTE. Note: ``checked_animal`` SELECTs ``fecha_alta`` so
# the regla 3 filter can run in the same statement.
_UPDATE_ACTUACION_SANITARIA_SQL: str = f"""
WITH checked_animal AS (
    SELECT id, fecha_alta FROM animales WHERE id = $2 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $3 AND activo = true
),
checked_tipo AS (
    SELECT id FROM catalogos_pruebas WHERE id = $5
),
updated AS (
    UPDATE actuacion_sanitaria AS target_actuacion SET
{", ".join(f"{col} = ${i + 2}" for i, col in enumerate(_WRITE_COLUMNS))},
updated_at = now()
    FROM checked_animal
    WHERE target_actuacion.id = $1
      AND (checked_animal.fecha_alta IS NULL OR checked_animal.fecha_alta::date <= $4::date)
      AND ($3::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
      AND ($5::text IS NULL OR EXISTS (SELECT 1 FROM checked_tipo))
    RETURNING {", ".join(_UPDATE_RETURNING_COLUMNS)}
)
SELECT {", ".join(_SELECT_COLUMNS)} FROM updated
"""  # noqa: S608 constant identifiers; values are $N binds


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock (D-HEALTH-03). Mirrors adopciones.
_DELETE_ACTUACION_SANITARIA_SQL: str = """
UPDATE actuacion_sanitaria
SET activo = false,
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


def _row_to_actuacion_sanitaria(row: dict[str, Any]) -> ActuacionSanitaria:
    return ActuacionSanitaria(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        fecha=str(row["fecha"]),
        tipo_actuacion_id=(
            str(row["tipo_actuacion_id"])
            if row.get("tipo_actuacion_id")
            else None
        ),
        veterinario=row.get("veterinario"),
        observaciones=row.get("observaciones"),
        voluntario_id=(
            str(row["voluntario_id"]) if row.get("voluntario_id") else None
        ),
        material_utilizado=row.get("material_utilizado"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _required_text(params: dict[str, Any], field: str) -> str:
    value = str(params.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required and cannot be empty")
    return value


def _optional_text(params: dict[str, Any], field: str) -> str | None:
    value = params.get(field)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _validate_fecha_d24(fecha: str) -> str | None:
    """Pure D-24 reglas 1+2 validation: format + future-date.

    Returns ``None`` when ``fecha`` is valid; returns a Spanish error
    message (suitable for surfacing to the operator via a 422 form
    re-render) when it violates one of the rules.

    **D-24 regla 3** (fecha anterior a ``animales.fecha_alta``) is NOT
    covered by this helper — that check needs the animal row, so it
    lives in the INSERT/UPDATE CTE (``checked_animal`` filter) and the
    disambiguation path of :func:`_raise_validation_error`. Splitting
    the validation in two layers keeps the no-DB validation cheap and
    the FK + fecha_alta check atomic with the write (CRITICAL-1).

    Parameters
    ----------
    fecha:
        The ``fecha`` value from the form, after ``_required_text`` has
        stripped whitespace. Empty / None callers should run ``_required_text``
        first; this helper assumes a non-empty string.
    """
    try:
        parsed = date.fromisoformat(fecha)
    except ValueError:
        return "fecha debe tener formato YYYY-MM-DD"
    if parsed > date.today():
        return f"fecha no puede ser futura (hoy es {date.today().isoformat()})"
    return None


def _build_write_params(params: dict[str, Any]) -> list[Any]:
    """Order matches ``_WRITE_COLUMNS`` for the INSERT/UPDATE placeholders."""
    return [
        _required_text(params, "animal_id"),
        _optional_text(params, "voluntario_id"),
        _required_text(params, "fecha"),
        _optional_text(params, "tipo_actuacion_id"),
        _optional_text(params, "veterinario"),
        _optional_text(params, "observaciones"),
        _optional_text(params, "material_utilizado"),
    ]


def _raise_validation_error(
    client: SqlExecutor, params: dict[str, Any]
) -> None:
    """Disambiguate a 0-row CTE result by re-running each check.

    Invoked ONLY after the atomic CTE returned 0 rows. The disambiguation
    SELECTs are NOT part of the success path, so the TOCTOU window for
    the success path remains closed. The disambiguation exists purely for
    operator UX: a specific error message lets the form re-render with a
    field-level hint instead of a generic "FK validation failed".

    Handles the D-24 regla 3 disambiguation too: if the animal exists,
    is active, AND has a ``fecha_alta`` that is after the form's ``fecha``,
    raise the D-24-specific message. The animal row's ``fecha_alta`` is
    formatted as ISO date for the operator-facing string.
    """
    animal_id = _required_text(params, "animal_id")
    animal_rows = client.execute_sql(
        "SELECT id, activo, fecha_alta FROM animales WHERE id = $1",
        [animal_id],
    )
    if not animal_rows:
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (no encontrado: {animal_id})"
        )
    if not animal_rows[0].get("activo", False):
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (inactivo: {animal_id})"
        )

    # Animal exists and is active. Now check D-24 regla 3:
    # fecha anterior a animales.fecha_alta (si fecha_alta no es NULL).
    fecha = _required_text(params, "fecha")
    fecha_alta_raw = animal_rows[0].get("fecha_alta")
    if fecha_alta_raw:
        try:
            fecha_parsed = date.fromisoformat(fecha)
        except ValueError:
            # _validate_fecha_d24 already raised on a bad format, so we
            # never reach this branch in practice. If we do (e.g. a
            # future caller bypasses _validate_fecha_d24), fall through to
            # the other checks instead of crashing with a confusing
            # date error here.
            fecha_parsed = None
        if fecha_parsed is not None:
            if isinstance(fecha_alta_raw, datetime):
                fecha_alta_date = fecha_alta_raw.date()
            else:
                fecha_alta_date = date.fromisoformat(str(fecha_alta_raw)[:10])
            if fecha_parsed < fecha_alta_date:
                raise ValueError(
                    f"fecha es anterior al alta del animal "
                    f"({fecha_alta_date.isoformat()})"
                )

    vol_id = _optional_text(params, "voluntario_id")
    if vol_id and not client.execute_sql(_CHECK_VOLUNTARIO_SQL, [vol_id]):
        raise ValueError(
            f"voluntario_id debe apuntar a un voluntario activo (inactivo: {vol_id})"
        )

    tipo_id = _optional_text(params, "tipo_actuacion_id")
    if tipo_id and not client.execute_sql(_CHECK_TIPO_ACTUACION_SQL, [tipo_id]):
        raise ValueError(
            f"tipo_actuacion_id no existe en catalogos_pruebas: {tipo_id}"
        )

    # Should not happen in practice (one of the SELECTs above would have
    # raised). Keep an explicit message so a future regression is loud,
    # not silent.
    raise ValueError(
        "FK validation failed (animal_id, voluntario_id, tipo_actuacion_id) — "
        "none matched"
    )


# --- public API -----------------------------------------------------------


def create_actuacion_sanitaria(
    client: SqlExecutor,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> ActuacionSanitaria:
    """Insert a new ``actuacion_sanitaria`` row in one CTE statement.

    The CTE bundles the FK checks (animal, voluntario, catalog) and the
    D-24 regla 3 check (``fecha`` vs ``animales.fecha_alta``) with the
    INSERT, so PostgreSQL evaluates them under a single statement
    snapshot — no window for the FK rows to be deactivated or for the
    animal's ``fecha_alta`` to change between the check and the write
    (CRITICAL-1).

    D-24 reglas 1+2 (format + future-date) are validated by
    :func:`_validate_fecha_d24` BEFORE the CTE so the operator gets a
    Spanish-friendly error message without a DB round-trip on the common
    form-validation failure.

    On 0 rows returned by the CTE (FK active-check failure OR D-24
    regla 3 violation), :func:`_raise_validation_error` runs targeted
    SELECTs to identify which check failed and raise a specific
    ``ValueError`` (mirrors the adopciones pattern).
    """
    _build_write_params(params)  # no-DB validation: raise before the SELECT

    fecha = _required_text(params, "fecha")
    fecha_error = _validate_fecha_d24(fecha)
    if fecha_error is not None:
        raise ValueError(fecha_error)

    rows = client.execute_sql(
        _INSERT_ACTUACION_SANITARIA_SQL, _build_write_params(params)
    )
    if not rows:
        _raise_validation_error(client, params)

    actuacion = _row_to_actuacion_sanitaria(rows[0])
    log_safe(
        "sanidad.created",
        actuacion_id=actuacion.id,
        animal_id=actuacion.animal_id,
        fecha=actuacion.fecha,
        actor_user_id=actor_user_id,
    )
    _post_create_schedule(client, actuacion)
    return actuacion


def list_actuaciones_sanitarias(
    client: SqlExecutor,
    *,
    animal_id: str | None = None,
) -> list[ActuacionSanitaria]:
    """Return active ``actuacion_sanitaria`` rows, most recent first.

    When ``animal_id`` is provided, delegates to
    :func:`search_actuaciones_by_animal` (the only path that uses the
    parameter). Otherwise returns the global list with ``LIMIT 100``,
    ordered by ``fecha_alta DESC``.

    P2-2 (risk review 2026-07-04): hard ``LIMIT 100`` cap so a malicious
    or runaway caller cannot dump the whole table.
    """
    if animal_id:
        return search_actuaciones_by_animal(client, animal_id)
    rows = client.execute_sql(_LIST_ACTUACIONES_SANITARIAS_SQL)
    return [_row_to_actuacion_sanitaria(row) for row in rows]


def list_catalogos_pruebas(client: SqlExecutor) -> list[dict[str, Any]]:
    """Return active health-test catalog rows for sanidad forms.

    Routes must not import SQL-backed catalog helpers directly. Keeping this
    wrapper in the sanidad service preserves the route/service boundary while
    still reusing the canonical catalog query implementation.
    """
    return _list_catalogos_pruebas(client)


def list_catalogos_periodicidad(client: SqlExecutor) -> list[dict[str, Any]]:
    """Return active periodicity rules for health tests (HEALTH-06 #55).

    The catalog is species-aware: each rule carries an ``especie`` field
    (``NULL`` = all species, ``'canina'`` or ``'felina'`` = specific).
    ``periodicidad_meses`` is ``NULL`` for one-shot operations
    (e.g. Esterilización) and a positive integer for recurring tests.

    Routes must not import SQL-backed catalog helpers directly. Keeping this
    wrapper in the sanidad service preserves the route/service boundary while
    still reusing the canonical catalog query implementation.
    """
    return _list_catalogos_periodicidad(client)


def get_actuacion_sanitaria_by_id(
    client: SqlExecutor, actuacion_id: str
) -> ActuacionSanitaria | None:
    """Return one ``actuacion_sanitaria`` by id (active or inactive), or ``None``."""
    rows = client.execute_sql(_GET_ACTUACION_BY_ID_SQL, [actuacion_id])
    return _row_to_actuacion_sanitaria(rows[0]) if rows else None


def update_actuacion_sanitaria(
    client: SqlExecutor,
    actuacion_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> ActuacionSanitaria | None:
    """Update an existing ``actuacion_sanitaria`` row in one CTE statement.

    Same single-snapshot CTE pattern as :func:`create_actuacion_sanitaria`
    (FK active checks + D-24 regla 3 + UPDATE atomic). Returns ``None``
    when the id does not exist (the UPDATE row count is 0 AND the
    disambiguation :func:`get_actuacion_sanitaria_by_id` SELECT is
    empty). On 0 rows due to a failed FK check or D-24 regla 3
    violation, :func:`_raise_validation_error` raises a specific
    ``ValueError``.

    D-24 reglas 1+2 are validated by :func:`_validate_fecha_d24` before
    the CTE, identical to the create path.
    """
    _build_write_params(params)

    fecha = _required_text(params, "fecha")
    fecha_error = _validate_fecha_d24(fecha)
    if fecha_error is not None:
        raise ValueError(fecha_error)

    rows = client.execute_sql(
        _UPDATE_ACTUACION_SANITARIA_SQL,
        [actuacion_id, *_build_write_params(params)],
    )
    if not rows:
        # Either the id is missing OR an FK / D-24 check failed. The id
        # check is cheap and disambiguates the common "404 vs 422"
        # path; we only run the broader disambiguation when the id is
        # actually present in the DB.
        if get_actuacion_sanitaria_by_id(client, actuacion_id) is None:
            return None
        _raise_validation_error(client, params)

    actuacion = _row_to_actuacion_sanitaria(rows[0])
    log_safe(
        "sanidad.updated",
        actuacion_id=actuacion.id,
        animal_id=actuacion.animal_id,
        fecha=actuacion.fecha,
        actor_user_id=actor_user_id,
    )
    return actuacion


def delete_actuacion_sanitaria(
    client: SqlExecutor,
    actuacion_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Atomically soft-delete an ``actuacion_sanitaria`` row.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the row does not exist OR was already
    inactive. The ``WHERE id = $1 AND activo = true`` filter folds the
    existence check into the same statement under PostgreSQL's row lock
    (D-HEALTH-03); two concurrent calls produce exactly one ``True`` and
    one ``False``.
    """
    rows = client.execute_sql(_DELETE_ACTUACION_SANITARIA_SQL, [actuacion_id])
    deactivated = bool(rows)
    if deactivated:
        log_safe(
            "sanidad.deleted",
            actuacion_id=actuacion_id,
            actor_user_id=actor_user_id,
        )
    return deactivated


def search_actuaciones_by_animal(
    client: SqlExecutor, animal_id: str
) -> list[ActuacionSanitaria]:
    """Return active ``actuacion_sanitaria`` rows for ``animal_id``.

    D-HEALTH-04: keyed by ``animal_id`` (UUID), ordered by ``fecha DESC``
    (most-recent clinical event first), capped at ``LIMIT 100``.

    The animal id is the FK key — there is no ILIKE search here because
    the animal's name / NCHIP live in the ``animales`` table and joining
    for a substring search is outside the scope of this slice. Future
    slices can add a ``?animal_nchip=`` filter via a JOIN if the
    operator-facing UX demands it.

    A whitespace-only or ``None`` ``animal_id`` returns ``[]`` without
    hitting the DB (no SQL roundtrip on an empty filter).
    """
    if not animal_id or not animal_id.strip():
        return []
    rows = client.execute_sql(_LIST_BY_ANIMAL_SQL, [animal_id.strip()])
    return [_row_to_actuacion_sanitaria(row) for row in rows]


# --- HEALTH-03 resumen (issue #52) -------------------------------------------


@dataclass(frozen=True, slots=True)
class SaludResumenItem:
    """A single tipo's latest actuacion for ``SaludResumen``."""

    tipo: str
    ultima_fecha: str
    ultimo_resultado: str | None
    ultima_descripcion: str | None
    producto: str | None


@dataclass(frozen=True, slots=True)
class SaludResumen:
    """The health-summary response for one animal (HEALTH-03, issue #52)."""

    animal_id: str
    nchip: str | None
    resumen: list[SaludResumenItem]


def _row_to_salud_resumen_item(row: dict[str, Any]) -> SaludResumenItem:
    return SaludResumenItem(
        tipo=str(row["tipo"]),
        ultima_fecha=str(row["ultima_fecha"]),
        ultimo_resultado=str(row["ultimo_resultado"]) if row.get("ultimo_resultado") else None,
        ultima_descripcion=str(row["ultima_descripcion"]) if row.get("ultima_descripcion") else None,
        producto=str(row["producto"]) if row.get("producto") else None,
    )


def get_resumen_sanitario(
    client: SqlExecutor,
    animal_id: str,
) -> SaludResumen:
    """Return the latest actuacion of each tipo for one animal.

    HEALTH-03 (issue #52): ``GET /animales/{animal_id}/salud/resumen``.
    For each ``catalogos_pruebas.observaciones`` (tipo) that has at least
    one active ``actuacion_sanitaria`` row for ``animal_id``, returns the
    most recent one (MAX fecha) with its resultado, description (codigo),
    and product (material_utilizado).

    Returns a ``SaludResumen`` with an empty ``resumen`` list when the
    animal has no actuaciones at all.
    """
    sql, params = queries.build_resumen_sanitario(animal_id)
    rows = client.execute_sql(sql, params)
    items = [_row_to_salud_resumen_item(row) for row in rows]

    nchip_sql, nchip_params = queries.build_get_animal_nchip(animal_id)
    animal_rows = client.execute_sql(nchip_sql, nchip_params)
    nchip = animal_rows[0]["nchip"] if animal_rows else None

    return SaludResumen(animal_id=animal_id, nchip=nchip, resumen=items)


@dataclass(frozen=True, slots=True)
class ProximaPrueba:
    """One row of the proximity report (issue #652).

    Mirrors the columns of ``build_proximas_pruebas_sql``: chip +
    nombre + tipo_codigo + fecha_ultima + fecha_proxima +
    periodicidad_meses. ``estado`` is derived in the service from
    ``fecha_proxima`` vs the operator-supplied ``fecha_hasta``.
    """

    chip: str
    nombre: str
    tipo_codigo: str
    fecha_ultima: date
    fecha_proxima: date
    periodicidad_meses: int
    estado: str


def _compute_estado(fecha_proxima: date, fecha_hasta: date) -> str:
    """Return one of ``vencida`` / ``proxima`` / ``futura``.

    ``vencida``: ``fecha_proxima`` is strictly before ``fecha_hasta``
    (the operator already missed the deadline relative to the window).
    ``proxima``: ``fecha_proxima`` falls within 30 days after
    ``fecha_hasta`` — the test is coming up soon and the operator
    should see it on the dashboard.
    ``futura``: anything further out than 30 days past ``fecha_hasta`` —
    lower priority.

    The 30-day window matches the dashboard's "salud" tile
    threshold (issue #52): the operator uses the report to triage the
    next month of work, not to plan the year.
    """
    if fecha_proxima < fecha_hasta:
        return "vencida"
    if fecha_proxima <= fecha_hasta + timedelta(days=30):
        return "proxima"
    return "futura"


def _row_to_proxima_prueba(
    row: dict[str, Any],
    fecha_hasta: date,
) -> ProximaPrueba:
    """Map one row of ``build_proximas_pruebas_sql`` to ProximaPrueba."""
    return ProximaPrueba(
        chip=row["chip"],
        nombre=row["nombre"],
        tipo_codigo=row["tipo_codigo"],
        fecha_ultima=row["fecha_ultima"],
        fecha_proxima=row["fecha_proxima"],
        periodicidad_meses=row["periodicidad_meses"],
        estado=_compute_estado(row["fecha_proxima"], fecha_hasta),
    )


def get_proximas_pruebas(
    client: SqlExecutor,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    animal_id: str | None = None,
    tipo_prueba_codigo: str | None = None,
) -> list[ProximaPrueba]:
    """Return one ``ProximaPrueba`` per (animal, tipo_prueba) combination
    whose next due date falls in ``[fecha_desde, fecha_hasta]``.

    See ``build_proximas_pruebas_sql`` for the SQL contract (what the
    query joins, what it excludes). This function adds: the SQL
    round-trip and the row-to-dataclass projection with the derived
    ``estado`` column.

    Args:
        client: the SqlExecutor (production ``LocalPostgresExecutor`` or the
            integration conftest's ``self_host_schema``).
        fecha_desde: lower bound of the window (inclusive).
        fecha_hasta: upper bound (inclusive). Also drives the
            ``estado`` derivation (see ``_compute_estado``).
        animal_id: optional filter by animal.
        tipo_prueba_codigo: optional filter by ``catalogos_periodicidad.codigo``.

    Returns an empty list when the window has no rows or when filters
    exclude every row. Order: ``fecha_proxima ASC`` (most-overdue
    first), as established by the builder.
    """
    sql, params = queries.build_proximas_pruebas_sql(
        fecha_desde,
        fecha_hasta,
        animal_id=animal_id,
        tipo_prueba_codigo=tipo_prueba_codigo,
    )
    rows = client.execute_sql(sql, params)
    return [_row_to_proxima_prueba(row, fecha_hasta) for row in rows]
