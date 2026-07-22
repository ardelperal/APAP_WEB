"""Service layer for ADOPT-01 adopciones (CRUD).

Owns SQL, validation, FK checks, mapping, and soft-delete for the
``adopciones`` table (legacy ``TbAdopcion`` mirror, verified via
Dysflow ``projectId=apap`` on 2026-07-04 — 14 legacy columns + 2
justified improvements: structured ``dni_adoptante`` /
``telefono_adoptante`` / ``email_adoptante`` instead of a single
free-text blob, and a structured FK to ``voluntarios`` for the
seguimiento role). The ``tipo_adopcion`` column is added by migration
``005_add_tipo_adopcion.sql`` (D-ADOPT-01).

Validation contract (mirrors INTAKE-01 style):

- Required: ``animal_id``, ``fecha_adopcion``, ``nombre_adoptante`` (the
  only mandatory adoptante field per discovery 2.3).
- ``animal_id`` MUST reference an active ``animales`` row (FK check).
- ``voluntario_seguimiento_id`` is optional. When provided, it MUST
  reference an active ``voluntarios`` row (VOL-05, D-ADOPT-02). A
  deactivated volunteer must not be assigned to a new adoption.
- ``entrada_origen_id`` is optional. When provided, it MUST reference
  an existing ``entradas`` row (FK check). Soft-deleted entradas are
  accepted (the legacy mapping layer needs to find them even after a
  soft-delete, mirroring ``acogidas._validate_entrada_exists_if_present``).
- ``tipo_adopcion`` is constrained by a DB CHECK constraint to one of
  ``{'regular', 'preadopcion', 'judicial'}``; the service does not
  validate it (the DB raises, the route surfaces as 422).
- ``donativo_preadopcion`` / ``donativo_adopcion`` are numeric; non-
  numeric inputs raise ``ValueError``.
- Empty strings (after ``.strip()``) count as missing for required
  fields.
- Soft-delete via ``activo = false`` + ``updated_at = now()``; physical
  deletes are forbidden (project-wide pattern).
- ``is_active`` is derived (``fecha_devolucion is None``), not
  persisted (D-ADOPT-05).
- ``search_adopciones_by_adoptante`` is case-insensitive (``ILIKE``,
  D-ADOPT-04) with wildcard escaping (P1 risk review 2026-07-04) and
  a hard ``LIMIT 100`` cap (CRITICAL-2 + P2-2).

CRITICAL-1 (P1 reliability, review 2026-07-04): create / update run
validation + write in a single CTE so PostgreSQL's statement-level
snapshot eliminates the TOCTOU window between the FK SELECTs and the
INSERT / UPDATE. On 0 rows returned, the service runs targeted
disambiguation SELECTs to raise a specific ``ValueError`` for the
operator (the success path is atomic — the failure-path
disambiguation reads are operator-UX only).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.insforge import InsForgeError
from app.core.logging import log_safe


class AdopcionConflictError(ValueError):
    """Raised from ``create_adopcion`` / ``update_adopcion`` on UNIQUE
    ``(animal_id, fecha_adopcion)`` violations (issue #47, P1 readability
    review 2026-07-04).

    The service maps the InsForge 409 envelope to this domain-meaningful
    exception; the route translates it to a 409 form re-render (mirrors
    ``EntradaConflictError`` in entradas and ``CesionConflictError`` in
    cesiones). Carries the original ``InsForgeError`` as ``__cause__`` so
    operators can still inspect the raw DB response when needed.
    """


@dataclass(frozen=True, slots=True)
class Adopcion:
    """A public service-row representation for ``adopciones``."""

    id: str
    animal_id: str
    fecha_adopcion: str
    nombre_adoptante: str
    activo: bool = True
    voluntario_seguimiento_id: str | None = None
    fecha_devolucion: str | None = None
    donativo_preadopcion: float | None = None
    donativo_adopcion: float | None = None
    dni_adoptante: str | None = None
    telefono_adoptante: str | None = None
    email_adoptante: str | None = None
    entrada_origen_id: str | None = None
    observaciones: str | None = None
    tipo_adopcion: str = "regular"
    fecha_alta: str | None = None
    updated_at: str | None = None

    @property
    def is_active(self) -> bool:
        """``True`` when the adoption is still vigente (no return date).

        Derived (D-ADOPT-05), not persisted: a row can be
        ``activo = false`` in the DB (soft-deleted) AND still have
        ``fecha_devolucion`` set, but the inverse is what matters to the
        operator: "is this animal still with this family?". Once the
        family returns the animal, ``fecha_devolucion`` is set and the
        adoption is no longer vigente.
        """
        return self.fecha_devolucion is None


_WRITE_COLUMNS: tuple[str, ...] = (
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
)


_SELECT_COLUMNS: tuple[str, ...] = (
    "id",
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
    "fecha_alta",
    "updated_at",
    "activo",
)


# --- FK validation queries (defense in depth over the DB FK constraints) ---
# These run inside the CTE (see _INSERT_ADOPCION_SQL / _UPDATE_ADOPCION_SQL
# below) so PostgreSQL evaluates them under a single statement snapshot.
# They are also re-used by ``_raise_validation_error`` for the
# disambiguation path AFTER the CTE returns 0 rows.
_CHECK_ANIMAL_SQL: str = (
    "SELECT id FROM animales WHERE id = $1 AND activo = true"
)


_CHECK_VOLUNTARIO_SQL: str = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)


# entrada: existence only — soft-deleted entradas must still resolve so
# the legacy mapping layer can find them (mirrors the acogidas pattern).
_CHECK_ENTRADA_SQL: str = "SELECT id FROM entradas WHERE id = $1"


# --- Atomic write SQL (CRITICAL-1: validation + write in one CTE) ---------
# PostgreSQL evaluates every CTE under the same statement snapshot, so the
# INSERT (or UPDATE) sees the same view of animales / voluntarios /
# entradas as the FK checks. There is no window between the SELECT and
# the write for a concurrent admin to deactivate a row.
#
# Placeholders:
#   $1  animal_id          (required FK)
#   $2  voluntario_id      (optional FK; NULL when not provided)
#   $3  fecha_adopcion
#   $4  fecha_devolucion
#   $5  donativo_preadopcion
#   $6  donativo_adopcion
#   $7  nombre_adoptante
#   $8  dni_adoptante
#   $9  telefono_adoptante
#   $10 email_adoptante
#   $11 entrada_origen_id  (optional FK; NULL when not provided)
#   $12 observaciones
#   $13 tipo_adopcion
_INSERT_ADOPCION_SQL: str = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $1 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $2 AND activo = true
),
checked_entrada AS (
    SELECT id FROM entradas WHERE id = $11
),
inserted AS (
    INSERT INTO adopciones ({", ".join(_WRITE_COLUMNS)})
    SELECT
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
    FROM checked_animal
    WHERE
        ($2::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
        AND ($11::text IS NULL OR EXISTS (SELECT 1 FROM checked_entrada))
    RETURNING {", ".join(_SELECT_COLUMNS)}
)
SELECT {", ".join(_SELECT_COLUMNS)} FROM inserted
"""


# CRITICAL-2 + P2-2 (risk review 2026-07-04): bounded result set so a
# malicious or runaway caller cannot dump the whole table.
_LIST_ADOPCIONES_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC "
    "LIMIT 100"
)


# CRITICAL-2 + P2-2 (risk review 2026-07-04):
# - ``ESCAPE '\'`` so the bound parameter is treated literally (otherwise
#   ``%`` / ``_`` from a malicious or accidental input would become
#   wildcards).
# - ``nombre_parcial`` is escaped at the service layer
#   (``search_adopciones_by_adoptante``) before bind: ``\`` → ``\\``,
#   ``%`` → ``\%``, ``_`` → ``\_``.
# - Hard ``LIMIT 100`` cap so the search cannot DOS the table.
_LIST_ADOPCIONES_BY_ADOPTANTE_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "AND nombre_adoptante ILIKE '%' || $1 || '%' ESCAPE '\\' "
    "ORDER BY fecha_alta DESC "
    "LIMIT 100"
)


_GET_ADOPCION_BY_ID_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} FROM adopciones WHERE id = $1"
)


# Atomic update: FK checks + UPDATE in one CTE (mirrors the INSERT CTE).
# The id is $1; the write-params start at $2 (so the FK placeholders
# shift by one relative to the INSERT CTE).
_UPDATE_ADOPCION_SQL: str = f"""
WITH checked_animal AS (
    SELECT id FROM animales WHERE id = $2 AND activo = true
),
checked_voluntario AS (
    SELECT id FROM voluntarios WHERE id = $3 AND activo = true
),
checked_entrada AS (
    SELECT id FROM entradas WHERE id = $12
),
updated AS (
    UPDATE adopciones SET
{", ".join(f"{col} = ${i + 4}" for i, col in enumerate(_WRITE_COLUMNS))},
updated_at = now()
    WHERE id = $1
      AND EXISTS (SELECT 1 FROM checked_animal)
      AND ($3::text IS NULL OR EXISTS (SELECT 1 FROM checked_voluntario))
      AND ($12::text IS NULL OR EXISTS (SELECT 1 FROM checked_entrada))
    RETURNING {", ".join(_SELECT_COLUMNS)}
)
SELECT {", ".join(_SELECT_COLUMNS)} FROM updated
"""


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock. Mirrors
# ``app/modules/casas_acogida/service.py::_DELETE_CASA_SQL`` and
# ``app/modules/entradas/service.py::_DELETE_ENTRADA_SQL``.
_DELETE_ADOPCION_SQL: str = """
UPDATE adopciones
SET activo = false,
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


def _row_to_adopcion(row: dict[str, Any]) -> Adopcion:
    return Adopcion(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        voluntario_seguimiento_id=(
            str(row["voluntario_seguimiento_id"])
            if row.get("voluntario_seguimiento_id")
            else None
        ),
        fecha_adopcion=str(row["fecha_adopcion"]),
        fecha_devolucion=(
            str(row["fecha_devolucion"]) if row.get("fecha_devolucion") else None
        ),
        donativo_preadopcion=(
            float(row["donativo_preadopcion"])
            if row.get("donativo_preadopcion") is not None
            else None
        ),
        donativo_adopcion=(
            float(row["donativo_adopcion"])
            if row.get("donativo_adopcion") is not None
            else None
        ),
        nombre_adoptante=str(row["nombre_adoptante"]),
        dni_adoptante=row.get("dni_adoptante"),
        telefono_adoptante=row.get("telefono_adoptante"),
        email_adoptante=row.get("email_adoptante"),
        entrada_origen_id=(
            str(row["entrada_origen_id"])
            if row.get("entrada_origen_id")
            else None
        ),
        observaciones=row.get("observaciones"),
        tipo_adopcion=str(row.get("tipo_adopcion") or "regular"),
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


def _optional_numeric(
    params: dict[str, Any], field: str
) -> float | None:
    """Return a float for ``donativo_*`` fields, ``None`` if missing/blank.

    Raises ``ValueError`` if the value is not coercible to a number
    (mirrors the ``capacidad`` positive-int pattern in
    ``app/modules/foster/service.py``). Strings like ``"12.50"`` are
    accepted; ``True``/``False`` are rejected (bool is an int subclass
    and would silently coerce to 1.0 / 0.0).
    """
    value = params.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number, not a boolean")
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc


def _optional_date(params: dict[str, Any], field: str) -> str | None:
    """Return an ISO date string for ``fecha_devolucion``, ``None`` if missing.

    Empty string (``""``) and ``None`` are treated as missing. Any other
    string is returned verbatim — the DB will reject malformed dates
    with a CHECK / type error that the route surfaces as 422.
    """
    value = _optional_text(params, field)
    return value


def _build_write_params(params: dict[str, Any]) -> list[Any]:
    """Order matches ``_WRITE_COLUMNS`` for the INSERT/UPDATE placeholders."""
    return [
        _required_text(params, "animal_id"),
        _optional_text(params, "voluntario_seguimiento_id"),
        _required_text(params, "fecha_adopcion"),
        _optional_date(params, "fecha_devolucion"),
        _optional_numeric(params, "donativo_preadopcion"),
        _optional_numeric(params, "donativo_adopcion"),
        _required_text(params, "nombre_adoptante"),
        _optional_text(params, "dni_adoptante"),
        _optional_text(params, "telefono_adoptante"),
        _optional_text(params, "email_adoptante"),
        _optional_text(params, "entrada_origen_id"),
        _optional_text(params, "observaciones"),
        # ``tipo_adopcion`` is constrained by a DB CHECK; the service
        # accepts whatever the form sends (defaults to 'regular' via
        # the SQL default when missing). The CHECK ensures integrity.
        _optional_text(params, "tipo_adopcion") or "regular",
    ]


def _validate_entrada_exists_if_present(
    client: SqlExecutor, entrada_id: str | None
) -> None:
    """``entrada_origen_id``, if present, must reference an existing entrada.

    We do NOT check ``activo`` here — legacy entries can be soft-deleted,
    but the FK should still resolve. The mapping layer (entrada.yaml)
    needs to find the entrada even when it's been deactivated, so the
    relational link stays intact for historical queries. Mirrors
    ``app/modules/acogidas/service.py::_validate_entrada_exists_if_present``.

    P1 risk review 2026-07-04: prior to this helper, a bad / non-existent
    ``entrada_origen_id`` UUID slipped past the service and surfaced as a
    500 (InsForge FK violation). This helper turns the same condition into
    a clean 422 with a Spanish-friendly error message.
    """
    if entrada_id is None:
        return
    rows = client.execute_sql(_CHECK_ENTRADA_SQL, [entrada_id])
    if not rows:
        raise ValueError(
            f"entrada_origen_id does not reference an existing entrada: {entrada_id}"
        )


def _raise_validation_error(
    client: SqlExecutor, params: dict[str, Any]
) -> None:
    """Disambiguate a 0-row CTE result by re-running each check.

    Invoked ONLY after the atomic CTE returned 0 rows. The
    disambiguation SELECTs are NOT part of the success path, so the
    TOCTOU window for the success path remains closed. The
    disambiguation exists purely for operator UX: a specific error
    message lets the form re-render with a field-level hint instead of
    a generic "FK validation failed".
    """
    animal_id = _required_text(params, "animal_id")
    if not client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id]):
        raise ValueError("animal_id does not reference an active animal")

    vol_id = _optional_text(params, "voluntario_seguimiento_id")
    if vol_id and not client.execute_sql(_CHECK_VOLUNTARIO_SQL, [vol_id]):
        raise ValueError(
            "voluntario_seguimiento_id must reference an active volunteer"
        )

    ent_id = _optional_text(params, "entrada_origen_id")
    if ent_id and not client.execute_sql(_CHECK_ENTRADA_SQL, [ent_id]):
        raise ValueError(
            f"entrada_origen_id does not reference an existing entrada: {ent_id}"
        )

    # Should not happen in practice (one of the SELECTs above would have
    # raised). Keep an explicit message so a future regression is loud,
    # not silent.
    raise ValueError(
        "FK validation failed (animal_id, voluntario, entrada) — none matched"
    )


def _is_duplicate_error(exc: InsForgeError) -> bool:
    body = str(exc.body).lower()
    return exc.status_code == 409 and (
        "duplicate" in body
        or "adopciones_natural_key" in body
        or "unique" in body
    )


def _escape_like(value: str) -> str:
    r"""Escape PostgreSQL ``ILIKE`` wildcards in a bound parameter.

    The SQL is written with ``ESCAPE '\'`` (see
    ``_LIST_ADOPCIONES_BY_ADOPTANTE_SQL``), so backslash is the escape
    character. We must escape ``\`` FIRST so the new backslashes
    introduced for ``%`` and ``_`` are not themselves escaped on a
    second pass.
    """
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def create_adopcion(
    client: SqlExecutor,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Adopcion:
    """Insert a new adopción in one CTE-statement (TOCTOU-safe).

    The CTE bundles the FK checks (animal, voluntario, entrada) and the
    INSERT, so PostgreSQL evaluates them under a single statement
    snapshot — no window for the FK rows to be deactivated between the
    check and the write (CRITICAL-1, review 2026-07-04). On 0 rows,
    ``_raise_validation_error`` runs targeted SELECTs to identify which
    FK failed and raise a specific ``ValueError``.

    A ``UNIQUE (animal_id, fecha_adopcion)`` violation surfaces as
    ``AdopcionConflictError`` (mirrors the entradas pattern); any other
    ``InsForgeError`` propagates unchanged.

    P2-3 (risk review 2026-07-04): ``actor_user_id`` is emitted on every
    successful create so audit pipelines can attribute the change.
    """
    _build_write_params(params)  # no-DB validation: raise before the SELECT
    try:
        rows = client.execute_sql(
            _INSERT_ADOPCION_SQL, _build_write_params(params)
        )
    except InsForgeError as exc:
        if _is_duplicate_error(exc):
            raise AdopcionConflictError(
                "adopcion duplicada para animal_id y fecha_adopcion"
            ) from exc
        raise

    if not rows:
        _raise_validation_error(client, params)

    adopcion = _row_to_adopcion(rows[0])
    log_safe(
        "adopciones.created",
        adopcion_id=adopcion.id,
        animal_id=adopcion.animal_id,
        tipo_adopcion=adopcion.tipo_adopcion,
        actor_user_id=actor_user_id,
    )
    return adopcion


def list_adopciones(client: SqlExecutor) -> list[Adopcion]:
    """Return active adopciones, most recent first (hard LIMIT 100)."""
    rows = client.execute_sql(_LIST_ADOPCIONES_SQL)
    return [_row_to_adopcion(row) for row in rows]


def get_adopcion_by_id(
    client: SqlExecutor, adopcion_id: str
) -> Adopcion | None:
    """Return one adopción by id (active or inactive), or ``None``."""
    rows = client.execute_sql(_GET_ADOPCION_BY_ID_SQL, [adopcion_id])
    return _row_to_adopcion(rows[0]) if rows else None


def update_adopcion(
    client: SqlExecutor,
    adopcion_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Adopcion | None:
    """Update an existing adopción in one CTE-statement (TOCTOU-safe).

    Same single-snapshot CTE pattern as ``create_adopcion``. Returns
    ``None`` when the id does not exist (the UPDATE row count is 0 AND
    the disambiguation ``get_adopcion_by_id`` SELECT is empty). On 0
    rows due to a failed FK check, ``_raise_validation_error`` raises a
    specific ``ValueError``.

    P2-1 (risk review 2026-07-04): ``UNIQUE (animal_id, fecha_adopcion)``
    violations on update are translated to ``AdopcionConflictError``
    (same handler as create) so the route can render a 409 form instead
    of leaking a generic InsForge 500.
    """
    _build_write_params(params)
    try:
        rows = client.execute_sql(
            _UPDATE_ADOPCION_SQL,
            [adopcion_id, *_build_write_params(params)],
        )
    except InsForgeError as exc:
        if _is_duplicate_error(exc):
            raise AdopcionConflictError(
                "adopcion duplicada para animal_id y fecha_adopcion"
            ) from exc
        raise

    if not rows:
        # Either the id is missing OR an FK check failed. The id check
        # is cheap and disambiguates the common "404 vs 422" path; we
        # only run the broader disambiguation when the id is actually
        # present in the DB.
        if get_adopcion_by_id(client, adopcion_id) is None:
            return None
        _raise_validation_error(client, params)

    adopcion = _row_to_adopcion(rows[0])
    log_safe(
        "adopciones.updated",
        adopcion_id=adopcion.id,
        animal_id=adopcion.animal_id,
        actor_user_id=actor_user_id,
    )
    return adopcion


def delete_adopcion(
    client: SqlExecutor,
    adopcion_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Atomically soft-delete an adopción.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the row does not exist OR was already
    inactive. The ``WHERE id = $1 AND activo = true`` filter folds the
    existence check into the same statement under PostgreSQL's row
    lock (D-ADOPT-03); two concurrent calls produce exactly one
    ``True`` and one ``False``.

    P2-3 (risk review 2026-07-04): ``actor_user_id`` is emitted on every
    successful delete so audit pipelines can attribute the change.
    """
    rows = client.execute_sql(_DELETE_ADOPCION_SQL, [adopcion_id])
    deactivated = bool(rows)
    if deactivated:
        log_safe(
            "adopciones.deleted",
            adopcion_id=adopcion_id,
            actor_user_id=actor_user_id,
        )
    return deactivated


def search_adopciones_by_adoptante(
    client: SqlExecutor, nombre_parcial: str
) -> list[Adopcion]:
    """Return active adopciones whose ``nombre_adoptante`` matches (ILIKE).

    D-ADOPT-04: case-insensitive substring match via ``ILIKE`` with
    ``%parcial%`` on both sides, capped at ``LIMIT 100``.

    CRITICAL-2 + P2-2 (risk review 2026-07-04): ``nombre_parcial`` is
    escaped (backslash, percent, underscore) before being bound; the
    SQL uses ``ESCAPE '\\'`` so the bound parameter is treated as a
    literal substring. Whitespace-only filters return an empty list
    (no SQL roundtrip) — the route redirects to the full list in that
    case.

    The ``ILIKE`` operator without a trigram index is fine for the
    current ~400 adopciones/año volumetry. If the table grows beyond
    ~50k rows, add a ``pg_trgm`` GIN index on ``nombre_adoptante``
    (future optimization, not in this slice).
    """
    if not nombre_parcial or not nombre_parcial.strip():
        return []
    escaped = _escape_like(nombre_parcial.strip())
    rows = client.execute_sql(
        _LIST_ADOPCIONES_BY_ADOPTANTE_SQL, [escaped]
    )
    return [_row_to_adopcion(row) for row in rows]
