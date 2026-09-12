"""LocalBackend adapter implementing :class:`MaterialesPort`.

Hexagonal adapter (issue #752, PR 2 + PR 5): the only layer in the
materiales slice allowed to import ``SqlExecutor`` or anything
under ``app.core.local_backend``. PR 2 introduced the adapter;
PR 5 lifted the row-mapping and ``BackendError`` -> ``MaterialConflictError``
helpers that used to live in the legacy ``service.py`` into this
file so the adapter is self-contained.

Hexagonal taxonomy:

- **Domain**     (:mod:`app.modules.materiales.domain`)         — entities, no I/O.
- **Port**       (:mod:`app.modules.materiales.ports`)          — Protocol.
- **Adapter**    (this module)                                  — LocalBackend impl.
- **Application**(:mod:`app.modules.materiales.application`)   — use cases (PR 3).
- **DI**         (:mod:`app.modules.materiales.di`)             — wiring (PR 4).

Rule §22 (SQL/service separation): the SQL strings live in
``app.modules.materiales.queries``; this adapter calls those
builders — it does not compose SQL inline.

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

from typing import Any

from app.core._module_helpers._form_render import list_entities
from app.core.data_access import BackendError, SqlExecutor
from app.core.logging import log_safe
from app.modules.materiales import queries
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material

# --- helpers lifted from the legacy ``service.py`` (issue #752 PR 5) -------
#
# These helpers used to live in ``app.modules.materiales.service``; the
# hexagonal refactor moved the validation policy to the application use
# cases (PR 3) and the SQL composition to this adapter (PR 4). PR 5
# removes ``service.py`` entirely, so the row-mapping and
# ``BackendError`` -> ``MaterialConflictError`` translation that the
# adapter still needs land here. They are private (``_`` prefix) and
# are NOT part of the application surface — every use case calls the
# adapter, and the adapter composes these helpers itself.


def _row_to_material(row: dict[str, Any]) -> Material:
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
    return EstanciaMaterial(
        id=str(row["id"]),
        estancia_id=str(row["estancia_id"]),
        material_id=str(row["material_id"]),
        cantidad=int(row["cantidad"]),
        notas=row.get("notas"),
        activo=bool(row.get("activo", True)),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
    )


def _is_unique_violation(exc: BackendError) -> bool:
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


def _validate_estancia_open_and_active(
    client: SqlExecutor, estancia_id: str
) -> None:
    """Estancia must exist, be active, and have no fecha_final.

    PR 5 moved this helper from the legacy ``service.py`` to the
    adapter. The application use case still calls it via the port
    surface (``estancia_is_open_and_active``); this private version
    is a safety net retained for any future use case that bypasses
    the protocol surface (none today). The 23505 / unique-violation
    translation lives in ``_is_unique_violation``.
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
    """Material must exist and be active (PR 5 helper)."""
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


class LocalBackendMaterialesAdapter:
    """Adapter that satisfies :class:`MaterialesPort` against LocalBackend.

    Holds a reference to the SQL executor (typically a
    :class:`LocalPostgresExecutor`) and delegates each public method
    to the SQL builders in :mod:`app.modules.materiales.queries` and
    the row-mapping helpers in this module. Constructor takes the
    executor only — no other state.

    The dataclass return types (``Material``, ``EstanciaMaterial``)
    and the exception raised on natural-key collisions
    (:class:`MaterialConflictError`) are imported from the slice's
    ``domain/`` module (PR 1). The mapper and validator helpers
    (``_row_to_*``, ``_is_unique_violation``, ``_validate_*``) live
    at the top of this file (PR 5 lifted them from the legacy
    ``service.py`` so the adapter is self-contained).

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
