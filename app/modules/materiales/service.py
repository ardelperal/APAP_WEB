"""Catalog service and shared persistence primitives for FOSTER-04 (Refs #46).

Owns catalog CRUD for ``materiales`` plus the SQL, mapping, and validation
primitives shared with ``estancia_material_service``. Public junction CRUD
lives in that dedicated service.

Legacy contract (P1 fidelity to ``TbMaterial`` per
``docs/proceso.md`` premise P1 + ``data-model-completeness.md`` §4):

- The catalog mirrors ``TbMaterial`` 1:1: ``material / tamano / color``
  as the legacy natural-key trio with DB-enforced ``UNIQUE (material,
  tamano, color)``; ``observaciones`` is the legacy free-text field
  (``TbMaterial.Observaciones``).
- The junction mirrors the legacy DB-enforced FK
  ``TbAcogidaAnimalMaterial.IDAcogida → TbAcogidaAnimal.IDAcogida``
  via ``estancia_id REFERENCES acogidas(id)`` + ``material_id
  REFERENCES materiales(id)``.

Validation contract (mirrors INTAKE-01 / FOSTER-01 / FOSTER-02 style):

- ``material`` / ``tamano`` / ``color`` are required, non-empty after
  ``.strip()``.
- ``observaciones`` is optional (free-text legacy field).
- ``cantidad`` is integer > 0 (CHECK constraint + Python validation
  defensively — Q4 in spec #15894).
- Assignment to a soft-deleted or closed estancia is rejected — the
  junction only allows assigning a material to an active estancia
  (``acogidas.activo = true AND fecha_final IS NULL``); see Q5 in
  spec #15894 and ``data-model-completeness.md`` §4.
- Assignment of an inactive material is rejected — see Scenario 8 in
  spec #15894.

Soft-delete pattern (matches ``app/modules/foster/service.py`` +
``app/modules/acogidas/service.py``):

- ``deactivate_material`` flips ``materiales.activo = false`` AND
  cascades the same flip to every active junction row pointing at the
  material. The cascade runs as a separate UPDATE on the junction
  table (atomic in the same InsForge transaction when the SQL is
  composed at the HTTP layer; inside ``execute_sql`` the two UPDATEs
  are sequenced so the operator's view of "the material is gone from
  everywhere" is consistent). See Scenario 6 in spec #15894.
- ``estancia_material_service.remove_material_from_estancia`` flips a single
  junction row's ``activo = false``. It is idempotent (returns False on
  missing / already-inactive).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Final

from app.core.data_access import SqlExecutor
from app.core.forms import optional_text as _optional_text
from app.core.forms import required_text
from app.core.insforge import InsForgeError
from app.core.logging import log_safe

_required_text = partial(
    required_text, error_template="{field} es obligatorio y no puede estar vacio"
)

# --- exceptions ----------------------------------------------------------


class MaterialConflictError(ValueError):
    """Raised when a natural-key conflict occurs on the catalog.

    The ``UNIQUE (material, tamano, color)`` constraint is DB-enforced
    (P1 fidelity to legacy ``TbMaterial``), so a duplicate INSERT
    raises PostgreSQL 23505 which the InsForge proxy surfaces as
    ``InsForgeError(409, ...)``. The service catches that and re-raises
    as ``MaterialConflictError`` with a Spanish actionable message so
    the route layer can map it to HTTP 409. Mirrors the
    ``EntradaConflictError`` / ``AcogidaConflictError`` precedent.
    """


# --- dataclasses ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Material:
    """A public service-row representation for ``materiales``."""

    id: str
    material: str
    tamano: str
    color: str
    activo: bool = True
    observaciones: str | None = None
    fecha_alta: str | None = None
    fecha_baja: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class EstanciaMaterial:
    """A public service-row representation for ``estancia_materiales``.

    The junction carries the assignment metadata (cantidad, notas)
    but does NOT denormalize the material name — callers that need the
    human-readable material name must JOIN via
    ``materiales.material`` separately. Keeping the dataclass narrow
    matches the precedent in ``app/modules/foster/assignment.py``.
    """

    id: str
    estancia_id: str
    material_id: str
    cantidad: int
    activo: bool = True
    notas: str | None = None
    fecha_alta: str | None = None


# --- catalog SQL columns -------------------------------------------------


_MATERIAL_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "material",
    "tamano",
    "color",
    "observaciones",
)


_MATERIAL_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "material",
    "tamano",
    "color",
    "observaciones",
    "activo",
    "fecha_alta",
    "fecha_baja",
    "updated_at",
)


# --- catalog SQL constants ----------------------------------------------


_MATERIAL_INSERT_SQL: Final[str] = (
    f"INSERT INTO materiales ({', '.join(_MATERIAL_WRITE_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(_MATERIAL_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(_MATERIAL_SELECT_COLUMNS)}"
)


_MATERIAL_GET_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(_MATERIAL_SELECT_COLUMNS)} "
    "FROM materiales WHERE id = $1"
)


# Default list — active-only. The inactive-filter version is the
# _MATERIAL_LIST_ALL_SQL below; activos_solo=True (default) routes to
# this one and activos_solo=False routes to the all-rows variant.
_MATERIAL_LIST_FILTER_ACTIVE_SQL: Final[str] = (
    f"SELECT {', '.join(_MATERIAL_SELECT_COLUMNS)} "
    "FROM materiales "
    "WHERE activo = true "
    "ORDER BY fecha_alta DESC"
)


_MATERIAL_LIST_ALL_SQL: Final[str] = (
    f"SELECT {', '.join(_MATERIAL_SELECT_COLUMNS)} "
    "FROM materiales "
    "ORDER BY fecha_alta DESC"
)


# Atomic soft-delete: existence check + deactivation in one statement
# under PostgreSQL's row lock. Mirrors
# ``app/modules/foster/service.py::_DELETE_CASA_SQL`` + the
# ``acogidas`` precedent.
_MATERIAL_DEACTIVATE_SQL: Final[str] = """
UPDATE materiales
SET activo = false,
    fecha_baja = now(),
    updated_at = now()
WHERE id = $1 AND activo = true
RETURNING id
"""


# Cascade: soft-delete every active junction row pointing at this
# material. Runs AFTER the catalog UPDATE so the material row is
# already inactive when the cascade flips the junctions (defensive
# ordering — a partial failure between the two would leave the
# material inactive but the junction rows visible to list, which is
# recoverable; the inverse (junctions flipped first then catalog
# UPDATE failing) would orphan the catalog row in a confusing state).
_MATERIAL_CASCADE_DEACTIVATE_SQL: Final[str] = """
UPDATE estancia_materiales
SET activo = false
WHERE material_id = $1 AND activo = true
RETURNING id
"""


# --- junction SQL columns ------------------------------------------------


_JUNCTION_WRITE_COLUMNS: Final[tuple[str, ...]] = (
    "estancia_id",
    "material_id",
    "cantidad",
    "notas",
)


_JUNCTION_SELECT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "estancia_id",
    "material_id",
    "cantidad",
    "notas",
    "fecha_alta",
    "activo",
)


# --- junction SQL constants ---------------------------------------------


_JUNCTION_INSERT_SQL: Final[str] = (
    f"INSERT INTO estancia_materiales ({', '.join(_JUNCTION_WRITE_COLUMNS)}) "
    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(_JUNCTION_WRITE_COLUMNS)))}) "
    f"RETURNING {', '.join(_JUNCTION_SELECT_COLUMNS)}"
)


_JUNCTION_GET_BY_ID_SQL: Final[str] = (
    f"SELECT {', '.join(_JUNCTION_SELECT_COLUMNS)} "
    "FROM estancia_materiales WHERE id = $1"
)


_JUNCTION_LIST_FOR_ESTANCIA_SQL: Final[str] = (
    f"SELECT {', '.join(_JUNCTION_SELECT_COLUMNS)} "
    "FROM estancia_materiales "
    "WHERE estancia_id = $1 AND activo = true "
    "ORDER BY fecha_alta DESC"
)


# Used by ``list_materials_for_estancia(activos_solo=False)`` for the
# admin view in Fase 6c (Q-T1). PR A exposes the active-only default.
_JUNCTION_LIST_FOR_ESTANCIA_ALL_SQL: Final[str] = (
    f"SELECT {', '.join(_JUNCTION_SELECT_COLUMNS)} "
    "FROM estancia_materiales "
    "WHERE estancia_id = $1 "
    "ORDER BY fecha_alta DESC"
)


# Atomic soft-delete (idempotent).
_JUNCTION_DEACTIVATE_SQL: Final[str] = """
UPDATE estancia_materiales
SET activo = false
WHERE id = $1 AND activo = true
RETURNING id
"""


# Cascade by material — same shape as the catalog cascade but exposed
# as a separate constant for clarity at the call site that wants to
# re-cascade without re-deactivating the catalog (e.g. a manual
# audit-log replay).
_JUNCTION_CASCADE_DEACTIVATE_BY_MATERIAL_SQL: Final[str] = (
    _MATERIAL_CASCADE_DEACTIVATE_SQL
)


# --- FK existence checks (read-only, no writes) -------------------------


# Validate the estancia EXISTS — the service then checks ``activo`` +
# ``fecha_final`` explicitly so the rejection works against test mocks
# that don't simulate the WHERE clause. Mirrors
# ``app/modules/acogidas/service.py::_CHECK_*_SQL``.
_ESTANCIA_OPEN_AND_ACTIVE_SQL: Final[str] = (
    "SELECT id, activo, fecha_final FROM acogidas WHERE id = $1"
)


# Same pattern as the estancia check — the service reads ``activo``
# from the row and rejects when it is False. Mirrors
# ``app/modules/foster/service.py::_CHECK_*_SQL`` precedent.
_MATERIAL_ACTIVE_SQL: Final[str] = (
    "SELECT id, activo FROM materiales WHERE id = $1"
)


# --- mapping --------------------------------------------------------------


def _row_to_material(row: dict[str, Any]) -> Material:
    """Map a ``materiales`` SELECT result row to a Material dataclass.

    Matches the ``_row_to_*`` regex so the CRITICAL_HELPERS coverage
    gate (``scripts/pytest_plugin/coverage_gate.py``) auto-discovers
    this helper and enforces 100% line coverage. Every branch maps
    the 9 columns declared in ``MATERIALES_CREATE_TABLE_SQL``.
    """
    return Material(
        id=str(row["id"]),
        material=str(row["material"]),
        tamano=str(row["tamano"]),
        color=str(row["color"]),
        observaciones=row.get("observaciones"),
        activo=bool(row.get("activo", True)),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        fecha_baja=str(row["fecha_baja"]) if row.get("fecha_baja") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _row_to_estancia_material(row: dict[str, Any]) -> EstanciaMaterial:
    """Map an ``estancia_materiales`` SELECT row to an EstanciaMaterial.

    Matches the ``_row_to_*`` regex — same coverage gate as
    ``_row_to_material``.
    """
    return EstanciaMaterial(
        id=str(row["id"]),
        estancia_id=str(row["estancia_id"]),
        material_id=str(row["material_id"]),
        cantidad=int(row["cantidad"]),
        notas=row.get("notas"),
        activo=bool(row.get("activo", True)),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
    )


# --- domain-specific validation helpers ----------------------------------


def _validate_cantidad(value: Any) -> int:
    """Validate the ``cantidad`` parameter for the junction.

    Mirrors ``app/modules/foster/service.py::_validate_capacidad``.
    Integer > 0; ``bool`` is rejected explicitly (Python's ``bool`` is
    an ``int`` subclass, so ``True`` would otherwise pass as ``1``).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("cantidad debe ser un entero positivo (>= 1)")
    return value


def _is_unique_violation(exc: InsForgeError) -> bool:
    """Detect a PostgreSQL 23505 unique-violation surfaced by InsForge.

    Mirrors the ``_is_duplicate_error`` precedent in
    ``app/modules/entradas/service.py``. InsForge's body shape is
    ``{"code": "23505", "message": "..."}`` for constraint violations.
    """
    body = exc.body
    if isinstance(body, dict):
        code = str(body.get("code", ""))
        message = str(body.get("message", "")).lower()
        return code == "23505" or "duplicate" in message or "unique" in message
    body_text = str(body).lower()
    return (
        exc.status_code == 409
        and ("duplicate" in body_text or "unique" in body_text)
    )


# --- catalog write helpers -----------------------------------------------


def _build_material_write_params(params: dict[str, Any]) -> list[Any]:
    """Order matches ``_MATERIAL_WRITE_COLUMNS`` for the INSERT placeholders."""
    return [
        _required_text(params, "material"),
        _required_text(params, "tamano"),
        _required_text(params, "color"),
        _optional_text(params, "observaciones"),
    ]


def _build_material_update_sql(
    params: dict[str, Any],
) -> tuple[str, list[Any]]:
    """Build the dynamic UPDATE SQL for ``materiales``.

    Only the keys actually present in ``params`` are written — this
    is the partial-update contract (omitting ``observaciones`` leaves
    it untouched). The catalog's PK + ``updated_at`` bump are
    unconditional; ``activo``, ``fecha_alta``, ``fecha_baja`` are NOT
    in the write set (those are managed by ``deactivate_material``
    and the DB defaults).
    """
    set_columns = tuple(
        col for col in _MATERIAL_WRITE_COLUMNS if col in params
    )
    if not set_columns:
        raise ValueError(
            "update_material requires at least one writable field "
            "(material / tamano / color / observaciones)"
        )
    sql = (
        "UPDATE materiales SET "
        + ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(set_columns))
        + ", updated_at = now() "
        + "WHERE id = $1 "
        + "RETURNING " + ", ".join(_MATERIAL_SELECT_COLUMNS)
    )

    # Build the param list in the same order as set_columns. Re-validate
    # each field through the same helpers used at create-time so an
    # empty-string update still raises.
    param_extractors: dict[str, Any] = {
        "material": lambda: _required_text(params, "material"),
        "tamano": lambda: _required_text(params, "tamano"),
        "color": lambda: _required_text(params, "color"),
        "observaciones": lambda: _optional_text(params, "observaciones"),
    }
    write_params = [param_extractors[col]() for col in set_columns]
    return sql, write_params


# --- junction write helpers ----------------------------------------------


def _build_junction_write_params(
    estancia_id: str,
    material_id: str,
    cantidad: int,
    notas: str | None,
) -> list[Any]:
    """Order matches ``_JUNCTION_WRITE_COLUMNS`` for the INSERT placeholders."""
    return [estancia_id, material_id, _validate_cantidad(cantidad), notas]


# --- FK validators --------------------------------------------------------


def _validate_estancia_open_and_active(
    client: SqlExecutor, estancia_id: str
) -> None:
    """Estancia must be active AND sin fecha_final to accept materials.

    Q5 in spec #15894 — assigning to a soft-deleted or closed stay is
    rejected at the service layer (the route layer surfaces the
    ValueError as 422). Mirrors the foster/acogidas precedent: the SQL
    does the existence check, the Python reads ``activo`` and
    ``fecha_final`` explicitly so the rejection works against test
    mocks that don't simulate the WHERE clause.
    """
    rows = client.execute_sql(_ESTANCIA_OPEN_AND_ACTIVE_SQL, [estancia_id])
    if not rows:
        raise ValueError(
            f"estancia_id debe apuntar a una estancia activa y sin "
            f"fecha_final (no encontrada: {estancia_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"estancia_id debe apuntar a una estancia activa y sin "
            f"fecha_final (inactiva: {estancia_id})"
        )
    if rows[0].get("fecha_final"):
        raise ValueError(
            f"estancia_id debe apuntar a una estancia activa y sin "
            f"fecha_final (cerrada: {estancia_id})"
        )


def _validate_material_active(
    client: SqlExecutor, material_id: str
) -> None:
    """Material must be active to be assignable.

    Scenario 8 in spec #15894 — assigning an inactive material is
    rejected at the service layer (the route layer surfaces the
    ValueError as 422). Same Python-side ``activo`` check pattern as
    the estancia validator.
    """
    rows = client.execute_sql(_MATERIAL_ACTIVE_SQL, [material_id])
    if not rows:
        raise ValueError(
            f"material_id debe apuntar a un material activo "
            f"(no encontrado: {material_id})"
        )
    if not rows[0].get("activo", False):
        raise ValueError(
            f"material_id debe apuntar a un material activo "
            f"(inactivo: {material_id})"
        )


# --- catalog CRUD ---------------------------------------------------------


def create_material(
    client: SqlExecutor, params: dict[str, Any]
) -> Material:
    """Insert a new material in the catalog and return the persisted row.

    Validates the required text fields BEFORE SQL so a blank submission
    raises ``ValueError`` with the offending field name. If the
    ``UNIQUE (material, tamano, color)`` constraint rejects the INSERT
    (PostgreSQL 23505 — race-condition duplicate), translate the
    ``InsForgeError`` to ``MaterialConflictError`` so the route layer
    can map it to HTTP 409 (Scenario 2 in spec #15894).
    """
    write_params = _build_material_write_params(params)
    try:
        rows = client.execute_sql(_MATERIAL_INSERT_SQL, write_params)
    except InsForgeError as exc:
        if _is_unique_violation(exc):
            raise MaterialConflictError(
                "ya existe material con esa combinacion "
                "material+tamano+color"
            ) from exc
        raise
    material = _row_to_material(rows[0])
    log_safe(
        "materiales.created",
        material_id=material.id,
        material=material.material,
        tamano=material.tamano,
    )
    return material


def get_material_by_id(
    client: SqlExecutor, material_id: str
) -> Material | None:
    """Return one material by id (active or inactive), or None."""
    rows = client.execute_sql(_MATERIAL_GET_BY_ID_SQL, [material_id])
    return _row_to_material(rows[0]) if rows else None


def list_materials(
    client: SqlExecutor, activos_solo: bool = True
) -> list[Material]:
    """Return materials ordered by fecha_alta DESC.

    ``activos_solo=True`` (the default) returns only active rows — the
    list view of the catalog. ``activos_solo=False`` returns every row
    (active + inactive) — the admin / audit view used in Fase 6c.
    """
    sql = (
        _MATERIAL_LIST_FILTER_ACTIVE_SQL
        if activos_solo
        else _MATERIAL_LIST_ALL_SQL
    )
    rows = client.execute_sql(sql)
    return [_row_to_material(row) for row in rows]


def update_material(
    client: SqlExecutor,
    material_id: str,
    params: dict[str, Any],
) -> Material | None:
    """Update a material's text fields + bump ``updated_at``.

    Same partial-update contract as ``update_casa_acogida``: only the
    keys actually present in ``params`` are written. Required-text
    validators run BEFORE SQL so a blank submission raises
    ``ValueError`` without touching the DB. Returns ``None`` when no
    row matches the id.
    """
    sql, write_params = _build_material_update_sql(params)
    try:
        rows = client.execute_sql(sql, [material_id, *write_params])
    except InsForgeError as exc:
        if _is_unique_violation(exc):
            raise MaterialConflictError(
                "ya existe material con esa combinacion "
                "material+tamano+color"
            ) from exc
        raise
    if not rows:
        return None
    material = _row_to_material(rows[0])
    log_safe(
        "materiales.updated",
        material_id=material.id,
    )
    return material


def deactivate_material(
    client: SqlExecutor, material_id: str
) -> bool:
    """Atomically soft-delete a material AND cascade the junction rows.

    Returns ``True`` if the row was active and was deactivated.
    Returns ``False`` if the row does not exist OR was already inactive.

    The cascade UPDATE flips every active ``estancia_materiales`` row
    pointing at the material. Both UPDATEs run in sequence inside
    ``deactivate_material`` — the catalog UPDATE first, then the
    cascade (Scenario 6 in spec #15894). The catalog UPDATE folds the
    existence check + deactivation into a single statement under
    PostgreSQL's row lock; two concurrent calls produce exactly one
    ``True`` and one ``False``. The cascade is skipped when the
    catalog UPDATE returns no rows so a non-existent material does not
    fan out spurious UPDATE attempts.
    """
    catalog_rows = client.execute_sql(
        _MATERIAL_DEACTIVATE_SQL, [material_id]
    )
    deactivated = bool(catalog_rows)
    if deactivated:
        cascade_rows = client.execute_sql(
            _MATERIAL_CASCADE_DEACTIVATE_SQL, [material_id]
        )
        log_safe(
            "materiales.deactivated",
            material_id=material_id,
            cascade_count=len(cascade_rows),
        )
    return deactivated
