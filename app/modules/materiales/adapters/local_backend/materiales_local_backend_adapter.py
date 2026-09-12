"""LocalBackend adapter implementing :class:`MaterialesPort`.

Hexagonal adapter (PR 2 of issue #752): the only layer in the
materiales slice allowed to import ``SqlExecutor`` or anything
under ``app.core.local_backend``. The adapter composes the SQL
builders in :mod:`app.modules.materiales.queries` and the row
mappers in :mod:`app.modules.materiales.service` to satisfy the
:class:`~app.modules.materiales.ports.materiales_port.MaterialesPort`
Protocol.

Hexagonal taxonomy:

- **Domain**     (:mod:`app.modules.materiales.domain`)         — entities, no I/O.
- **Port**       (:mod:`app.modules.materiales.ports`)          — Protocol.
- **Adapter**    (this module)                                  — LocalBackend impl.
- **Application**(:mod:`app.modules.materiales.application`)   — use cases (PR 3).
- **DI**         (:mod:`app.modules.materiales.di`)             — wiring (PR 4).

Rule §22 (SQL/service separation): the SQL strings live in the
existing ``app.modules.materiales.queries`` module. This adapter
calls those builders — it does not compose SQL inline.

Rule §31 (domain depends on Protocol): the dataclasses and the
exception this adapter raises (``Material``, ``EstanciaMaterial``,
``MaterialConflictError``) live in ``domain/``; the adapter never
imports a transport type into its return signature.

Until PR 4 lands, the adapter is constructed nowhere — its sole
purpose in PR 2 is to satisfy the Protocol and to prove that the
existing behaviour migrates cleanly. PR 5 deletes the legacy
``service.py`` and ``estancia_material_service.py`` once the routes
use the DI-bound port instead.
"""

from __future__ import annotations

from app.core._module_helpers._form_render import list_entities
from app.core.data_access import BackendError, SqlExecutor
from app.core.logging import log_safe
from app.modules.materiales import queries
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material
from app.modules.materiales.service import (
    _is_unique_violation,
    _row_to_estancia_material,
    _row_to_material,
    _validate_estancia_open_and_active,
    _validate_material_active,
)


class LocalBackendMaterialesAdapter:
    """Adapter that satisfies :class:`MaterialesPort` against LocalBackend.

    Holds a reference to the SQL executor (typically a
    :class:`LocalPostgresExecutor`) and delegates each public method
    to the SQL builders + row mappers that already live in
    ``app.modules.materiales.queries`` and
    ``app.modules.materiales.service``. Constructor takes the
    executor only — no other state.

    The dataclass return types (``Material``, ``EstanciaMaterial``)
    and the exception raised on natural-key collisions
    (:class:`MaterialConflictError`) are imported from the slice's
    ``domain/`` module (PR 1). The mapper and validator helpers
    (``_row_to_*``, ``_is_unique_violation``,
    ``_validate_*``) are still defined in the legacy ``service.py``
    module; this adapter imports them for composition but PR 3 will
    move them to ``application/`` once the use cases own the
    validation policy.

    Thread-safe: no mutable state; the executor is held as a single
    attribute and is itself expected to be safe under the project's
    request-scoped semantics.
    """

    def __init__(self, client: SqlExecutor) -> None:
        """Store the executor used by every public method."""
        self._client = client

    # --- catalog CRUD -------------------------------------------------------

    def create_material(self, params: dict) -> Material:
        """Insert a new material; translate 23505 to :class:`MaterialConflictError`."""
        sql, write_params = queries.build_material_insert(params)
        try:
            rows = self._client.execute_sql(sql, write_params)
        except BackendError as exc:
            if _is_unique_violation(exc):
                raise MaterialConflictError(  # noqa: TRY003 — operator-facing diagnostic
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

    def get_material_by_id(self, material_id: str) -> Material | None:
        """Return one material by id (active or inactive), or ``None``."""
        sql, params = queries.build_material_get_by_id(material_id)
        rows = self._client.execute_sql(sql, params)
        return _row_to_material(rows[0]) if rows else None

    def list_materials(self, activos_solo: bool = True) -> list[Material]:
        """Return materials ordered by ``fecha_alta DESC``."""
        sql, params = queries.build_material_list(activos_solo)
        return list_entities(self._client, sql, params, _row_to_material)

    def update_material(
        self, material_id: str, params: dict
    ) -> Material | None:
        """Update a material's text fields; return ``None`` if no row matches."""
        sql, write_params = queries.build_material_update(material_id, params)
        try:
            rows = self._client.execute_sql(sql, [material_id, *write_params])
        except BackendError as exc:
            if _is_unique_violation(exc):
                raise MaterialConflictError(  # noqa: TRY003 — operator-facing diagnostic
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

    def deactivate_material(self, material_id: str) -> bool:
        """Soft-delete a material and cascade the deactivation to its junctions."""
        deact_sql, deact_params = queries.build_material_deactivate(material_id)
        catalog_rows = self._client.execute_sql(deact_sql, deact_params)
        deactivated = bool(catalog_rows)
        if deactivated:
            cascade_sql, cascade_params = queries.build_material_cascade_deactivate(
                material_id
            )
            cascade_rows = self._client.execute_sql(cascade_sql, cascade_params)
            log_safe(
                "materiales.deactivated",
                material_id=material_id,
                cascade_count=len(cascade_rows),
            )
        return deactivated

    # --- junction CRUD ------------------------------------------------------

    def assign_material_to_estancia(
        self,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> EstanciaMaterial:
        """Insert a junction row; reject inactive estancia or material."""
        _validate_estancia_open_and_active(self._client, estancia_id)
        _validate_material_active(self._client, material_id)

        sql, write_params = queries.build_junction_insert(
            estancia_id, material_id, cantidad, notas
        )
        try:
            rows = self._client.execute_sql(sql, write_params)
        except BackendError as exc:
            if _is_unique_violation(exc):
                raise MaterialConflictError(  # noqa: TRY003 — operator-facing diagnostic
                    "ese material ya esta asignado a esta estancia"
                ) from exc
            raise
        junction = _row_to_estancia_material(rows[0])
        log_safe(
            "materiales.assigned",
            estancia_id=estancia_id,
            material_id=material_id,
            cantidad=cantidad,
        )
        return junction

    def list_materials_for_estancia(
        self, estancia_id: str, activos_solo: bool = True
    ) -> list[EstanciaMaterial]:
        """Return junction rows for ``estancia_id`` ordered by fecha_alta DESC."""
        sql, params = queries.build_junction_list_for_estancia(
            estancia_id, activos_solo
        )
        rows = self._client.execute_sql(sql, params)
        return [_row_to_estancia_material(row) for row in rows]

    def remove_material_from_estancia(self, junction_id: str) -> bool:
        """Atomically soft-delete a single junction row (idempotent)."""
        sql, params = queries.build_junction_deactivate(junction_id)
        rows = self._client.execute_sql(sql, params)
        removed = bool(rows)
        if removed:
            log_safe(
                "materiales.unassigned",
                junction_id=junction_id,
            )
        return removed

    # --- FK probes (PR 3 of issue #752) ---------------------------------

    def estancia_is_open_and_active(self, estancia_id: str) -> bool:
        """Return ``True`` iff the estancia exists, is active, and has no ``fecha_final``.

        Mirrors the validation policy the legacy
        ``_validate_estancia_open_and_active`` enforced: existence +
        ``activo=True`` + ``fecha_final IS NULL`` collapse to a single
        boolean the application use case can short-circuit on.
        """
        rows = self._client.execute_sql(
            *queries.build_estancia_active(estancia_id)
        )
        if not rows:
            return False
        row = rows[0]
        return bool(row.get("activo")) and not row.get("fecha_final")

    def material_is_active(self, material_id: str) -> bool:
        """Return ``True`` iff the material exists and is active.

        Mirrors ``_validate_material_active``: existence + ``activo=True``.
        """
        rows = self._client.execute_sql(
            *queries.build_material_active(material_id)
        )
        if not rows:
            return False
        return bool(rows[0].get("activo"))


__all__ = ["LocalBackendMaterialesAdapter"]
