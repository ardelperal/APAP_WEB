"""Catalog service and shared persistence primitives for FOSTER-04 (Refs #46).

Owns catalog CRUD for ``materiales`` plus the dataclasses, mapping
helpers, and domain validation shared with the junction service
(``estancia_material_service``). Public junction CRUD lives in that
dedicated service.

Per AGENTS.md §22, **all SQL strings and parameter shaping live in
``queries.py``**; this module imports those builders, applies domain
validation, and talks to the client. The seam is testable: the shape
of the SQL is asserted in ``tests/test_materiales_queries.py`` without
spinning up transport.

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
  defensively — Q4 in spec #15894). The cantidad validator itself
  lives in ``queries.py`` because it is part of the SQL parameter
  contract; it is invoked transparently by ``build_junction_insert``.
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
  table (atomic in the same LocalBackend transaction when the SQL is
  composed at the HTTP layer; inside ``execute_sql`` the two UPDATEs
  are sequenced so the operator's view of "the material is gone from
  everywhere" is consistent). See Scenario 6 in spec #15894.
- ``estancia_material_service.remove_material_from_estancia`` flips a single
  junction row's ``activo = false``. It is idempotent (returns False on
  missing / already-inactive).

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here and in ``queries.py``.
"""

from __future__ import annotations

from typing import Any

from app.core._module_helpers._form_render import list_entities
from app.core.data_access import BackendError, SqlExecutor
from app.core.logging import log_safe
from app.modules.materiales import queries
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material

# --- exceptions ----------------------------------------------------------
# ``MaterialConflictError`` moved to ``app/modules/materiales/domain/exceptions.py``
# in PR 1 of issue #752. The legacy module re-imports it so the public
# surface (and every test that imports the exception from this module)
# keeps working unchanged until PR 5 deletes ``service.py``.


# --- dataclasses ---------------------------------------------------------
# Moved to app/modules/materiales/domain/ in PR 1 of issue #752. The
# legacy module re-imports them so the public surface (and every test
# that imports from ``app.modules.materiales.service``) keeps working
# unchanged until PR 5 deletes ``service.py``.


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


def _is_unique_violation(exc: BackendError) -> bool:
    """Detect a PostgreSQL 23505 unique-violation surfaced by LocalBackend.

    Mirrors the ``_is_duplicate_error`` precedent in
    ``app/modules/entradas/service.py``. LocalBackend's body shape is
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
    sql, params = queries.build_estancia_active(estancia_id)
    rows = client.execute_sql(sql, params)
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
    sql, params = queries.build_material_active(material_id)
    rows = client.execute_sql(sql, params)
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
    ``BackendError`` to ``MaterialConflictError`` so the route layer
    can map it to HTTP 409 (Scenario 2 in spec #15894).
    """
    sql, write_params = queries.build_material_insert(params)
    try:
        rows = client.execute_sql(sql, write_params)
    except BackendError as exc:
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
    sql, params = queries.build_material_get_by_id(material_id)
    rows = client.execute_sql(sql, params)
    return _row_to_material(rows[0]) if rows else None


def list_materials(
    client: SqlExecutor, activos_solo: bool = True
) -> list[Material]:
    """Return materials ordered by fecha_alta DESC.

    ``activos_solo=True`` (the default) returns only active rows — the
    list view of the catalog. ``activos_solo=False`` returns every row
    (active + inactive) — the admin / audit view used in Fase 6c.
    """
    sql, params = queries.build_material_list(activos_solo)
    return list_entities(client, sql, params, _row_to_material)


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
    sql, write_params = queries.build_material_update(material_id, params)
    try:
        rows = client.execute_sql(sql, [material_id, *write_params])
    except BackendError as exc:
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
    deact_sql, deact_params = queries.build_material_deactivate(material_id)
    catalog_rows = client.execute_sql(deact_sql, deact_params)
    deactivated = bool(catalog_rows)
    if deactivated:
        cascade_sql, cascade_params = queries.build_material_cascade_deactivate(
            material_id
        )
        cascade_rows = client.execute_sql(cascade_sql, cascade_params)
        log_safe(
            "materiales.deactivated",
            material_id=material_id,
            cascade_count=len(cascade_rows),
        )
    return deactivated
