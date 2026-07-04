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
  D-ADOPT-04).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.insforge import InsForgeClient, InsForgeError
from app.core.logging import log_safe


class AdopcionConflictError(ValueError):
    """Raised when a natural-key conflict occurs on (animal_id, fecha_adopcion).

    Currently unused at the service level (the route lets the DB-level
    unique violation surface as a 422), but kept for future parity and
    explicit signal to routes — mirrors the entradas / casas_acogida
    pattern.
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


# FK validation queries — the FK constraints at the DB level guarantee
# referential integrity; these checks additionally enforce the
# ``activo = true`` precondition per the discovery 2.3 contract and
# VOL-05 (D-ADOPT-02). A deactivated volunteer must not be assigned to
# a new adoption.
_CHECK_ANIMAL_SQL: str = (
    "SELECT id FROM animales WHERE id = $1 AND activo = true"
)


_CHECK_VOLUNTARIO_SQL: str = (
    "SELECT id FROM voluntarios WHERE id = $1 AND activo = true"
)


_INSERT_ADOPCION_SQL: str = (
    f"INSERT INTO adopciones ({', '.join(_WRITE_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(_SELECT_COLUMNS)}"
)


_LIST_ADOPCIONES_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC"
)


_LIST_ADOPCIONES_BY_ADOPTANTE_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} "
    "FROM adopciones "
    "WHERE activo = true "
    "AND nombre_adoptante ILIKE '%' || $1 || '%' "
    "ORDER BY fecha_alta DESC"
)


_GET_ADOPCION_BY_ID_SQL: str = (
    f"SELECT {', '.join(_SELECT_COLUMNS)} FROM adopciones WHERE id = $1"
)


_UPDATE_ADOPCION_SQL: str = (
    "UPDATE adopciones SET "
    + ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(_WRITE_COLUMNS))
    + ", updated_at = now() "
    + "WHERE id = $1 "
    + "RETURNING "
    + ", ".join(_SELECT_COLUMNS)
)


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


def _validate_references(client: InsForgeClient, params: dict[str, Any]) -> None:
    """Validate FKs to ``animales`` (required) and ``voluntarios`` (optional).

    D-ADOPT-02 mirrors the ``entradas._validate_references`` pattern:
    the FK constraint at the DB level guarantees referential integrity,
    but we additionally enforce ``activo = true`` here so the operator
    gets a clear ``ValueError`` rather than a generic FK violation.

    VOL-05: a deactivated volunteer must not be assigned to a new
    adoption; the check is ``activo = true`` (not just existence).
    """
    animal_id = _required_text(params, "animal_id")
    if not client.execute_sql(_CHECK_ANIMAL_SQL, [animal_id]):
        raise ValueError("animal_id does not reference an active animal")

    voluntario_id = _optional_text(params, "voluntario_seguimiento_id")
    if voluntario_id and not client.execute_sql(
        _CHECK_VOLUNTARIO_SQL, [voluntario_id]
    ):
        raise ValueError(
            "voluntario_seguimiento_id must reference an active volunteer"
        )


def _is_duplicate_error(exc: InsForgeError) -> bool:
    body = str(exc.body).lower()
    return exc.status_code == 409 and (
        "duplicate" in body
        or "adopciones_natural_key" in body
        or "unique" in body
    )


def create_adopcion(
    client: InsForgeClient, params: dict[str, Any]
) -> Adopcion:
    """Insert a new adopción and return the persisted row.

    Validates required fields, FK checks (animal activo, voluntario
    activo per VOL-05), then INSERTs and returns the row. A
    ``UNIQUE (animal_id, fecha_adopcion)`` violation surfaces as
    ``AdopcionConflictError`` (mirrors the entradas pattern); any other
    ``InsForgeError`` propagates unchanged.
    """
    _build_write_params(params)  # validation, no DB
    _validate_references(client, params)

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
    adopcion = _row_to_adopcion(rows[0])
    log_safe(
        "adopciones.created",
        adopcion_id=adopcion.id,
        animal_id=adopcion.animal_id,
        tipo_adopcion=adopcion.tipo_adopcion,
    )
    return adopcion


def list_adopciones(client: InsForgeClient) -> list[Adopcion]:
    """Return active adopciones, most recent first."""
    rows = client.execute_sql(_LIST_ADOPCIONES_SQL)
    return [_row_to_adopcion(row) for row in rows]


def get_adopcion_by_id(
    client: InsForgeClient, adopcion_id: str
) -> Adopcion | None:
    """Return one adopción by id (active or inactive), or ``None``."""
    rows = client.execute_sql(_GET_ADOPCION_BY_ID_SQL, [adopcion_id])
    return _row_to_adopcion(rows[0]) if rows else None


def update_adopcion(
    client: InsForgeClient,
    adopcion_id: str,
    params: dict[str, Any],
) -> Adopcion | None:
    """Update an existing adopción and return the updated row.

    Re-runs FK validation (animal activo, voluntario activo per VOL-05)
    so an inactive volunteer cannot be silently re-assigned via an
    edit. Returns ``None`` when the id does not exist (``UPDATE ...
    RETURNING`` with 0 rows).
    """
    _build_write_params(params)
    _validate_references(client, params)

    rows = client.execute_sql(
        _UPDATE_ADOPCION_SQL,
        [adopcion_id, *_build_write_params(params)],
    )
    if not rows:
        return None
    adopcion = _row_to_adopcion(rows[0])
    log_safe(
        "adopciones.updated",
        adopcion_id=adopcion.id,
        animal_id=adopcion.animal_id,
    )
    return adopcion


def delete_adopcion(client: InsForgeClient, adopcion_id: str) -> bool:
    """Atomically soft-delete an adopción.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the row does not exist OR was already
    inactive. The ``WHERE id = $1 AND activo = true`` filter folds the
    existence check into the same statement under PostgreSQL's row
    lock (D-ADOPT-03); two concurrent calls produce exactly one
    ``True`` and one ``False``.
    """
    rows = client.execute_sql(_DELETE_ADOPCION_SQL, [adopcion_id])
    deactivated = bool(rows)
    if deactivated:
        log_safe("adopciones.deleted", adopcion_id=adopcion_id)
    return deactivated


def search_adopciones_by_adoptante(
    client: InsForgeClient, nombre_parcial: str
) -> list[Adopcion]:
    """Return active adopciones whose ``nombre_adoptante`` matches (ILIKE).

    D-ADOPT-04: case-insensitive substring match via ``ILIKE`` with
    ``%parcial%`` on both sides. Whitespace-only filters return an
    empty list (no SQL roundtrip) — the route redirects to the full
    list in that case.

    The ``ILIKE`` operator without a trigram index is fine for the
    current ~400 adopciones/año volumetry. If the table grows beyond
    ~50k rows, add a ``pg_trgm`` GIN index on ``nombre_adoptante``
    (future optimization, not in this slice).
    """
    if not nombre_parcial or not nombre_parcial.strip():
        return []
    rows = client.execute_sql(
        _LIST_ADOPCIONES_BY_ADOPTANTE_SQL, [nombre_parcial.strip()]
    )
    return [_row_to_adopcion(row) for row in rows]
