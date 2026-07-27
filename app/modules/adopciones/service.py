"""Service layer for ADOPT-01 adopciones (CRUD).

Owns orchestration, validation, FK checks, mapping, and soft-delete for the
``adopciones`` table. Pure SQL construction and parameter shaping live in
``app.modules.adopciones.queries`` per AGENTS.md §22.

The table mirrors legacy ``TbAdopcion`` (verified via Dysflow
``projectId=apap`` on 2026-07-04) with structured adopter contact fields,
volunteer tracking, and ``tipo_adopcion`` from migration
``005_add_tipo_adopcion.sql``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.insforge import InsForgeError
from app.core.logging import log_safe
from app.modules.adopciones import queries


class AdopcionConflictError(ValueError):
    """Raised on UNIQUE ``(animal_id, fecha_adopcion)`` violations."""


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
        """Return whether the adoption remains current without a return date."""
        return self.fecha_devolucion is None


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


def _validate_entrada_exists_if_present(
    client: SqlExecutor, entrada_id: str | None
) -> None:
    if entrada_id is None:
        return
    sql, sql_params = queries.build_adopcion_check_entrada(entrada_id)
    rows = client.execute_sql(sql, sql_params)
    if not rows:
        raise ValueError(
            f"entrada_origen_id does not reference an existing entrada: {entrada_id}"
        )


def _raise_validation_error(client: SqlExecutor, params: dict[str, Any]) -> None:
    animal_id = _required_text(params, "animal_id")
    sql, sql_params = queries.build_adopcion_check_animal(animal_id)
    if not client.execute_sql(sql, sql_params):
        raise ValueError("animal_id does not reference an active animal")

    vol_id = _optional_text(params, "voluntario_seguimiento_id")
    if vol_id:
        sql, sql_params = queries.build_adopcion_check_voluntario(vol_id)
        if not client.execute_sql(sql, sql_params):
            raise ValueError(
                "voluntario_seguimiento_id must reference an active volunteer"
            )

    ent_id = _optional_text(params, "entrada_origen_id")
    if ent_id:
        sql, sql_params = queries.build_adopcion_check_entrada(ent_id)
        if not client.execute_sql(sql, sql_params):
            raise ValueError(
                f"entrada_origen_id does not reference an existing entrada: {ent_id}"
            )

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
    sql, sql_params = queries.build_adopcion_insert(params)
    try:
        rows = client.execute_sql(sql, sql_params)
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
    """Return active adopciones, most recent first."""
    sql, sql_params = queries.build_adopcion_list()
    rows = client.execute_sql(sql, sql_params)
    return [_row_to_adopcion(row) for row in rows]


def get_adopcion_by_id(
    client: SqlExecutor, adopcion_id: str
) -> Adopcion | None:
    sql, sql_params = queries.build_adopcion_get_by_id(adopcion_id)
    rows = client.execute_sql(sql, sql_params)
    return _row_to_adopcion(rows[0]) if rows else None


def update_adopcion(
    client: SqlExecutor,
    adopcion_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Adopcion | None:
    sql, sql_params = queries.build_adopcion_update(adopcion_id, params)
    try:
        rows = client.execute_sql(sql, sql_params)
    except InsForgeError as exc:
        if _is_duplicate_error(exc):
            raise AdopcionConflictError(
                "adopcion duplicada para animal_id y fecha_adopcion"
            ) from exc
        raise

    if not rows:
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
    sql, sql_params = queries.build_adopcion_delete(adopcion_id)
    rows = client.execute_sql(sql, sql_params)
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
    if not nombre_parcial or not nombre_parcial.strip():
        return []
    escaped = _escape_like(nombre_parcial.strip())
    sql, sql_params = queries.build_adopcion_search(escaped)
    rows = client.execute_sql(sql, sql_params)
    return [_row_to_adopcion(row) for row in rows]
