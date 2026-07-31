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
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.insforge import InsForgeError
from app.core.logging import log_safe
from app.modules.adopciones import queries


class AdopcionConflictError(ValueError):
    """Raised on UNIQUE ``(animal_id, fecha_adopcion)`` violations."""


# ---------------------------------------------------------------------------
# ADOPT-03: Seguimiento state machine enums (issue #49)
# ---------------------------------------------------------------------------


class SeguimientoEstado(StrEnum):
    """The 4 pinned states for adoption follow-up tracking.

    Independent of the animal's lifecycle state (ADOPTADO etc.).
    """
    PENDIENTE = "PENDIENTE"
    DOCUMENTO_ENTREGADO = "DOCUMENTO_ENTREGADO"
    DOCUMENTO_ADJUNTO = "DOCUMENTO_ADJUNTO"
    SEGUIMIENTO_COMPLETADO = "SEGUIMIENTO_COMPLETADO"


class SeguimientoAction(StrEnum):
    """The 3 actions that drive state transitions."""
    MARCAR_ENTREGADO = "marcar_entregado"
    ANEXAR = "anexar_documento"
    COMPLETAR = "completar"


# Derived transition map:VALID_TRANSITIONS[from_state][action] = to_state
# One source of truth per domain concept (§4).
_VALID_TRANSITIONS: dict[SeguimientoEstado, dict[SeguimientoAction, SeguimientoEstado]] = {
    SeguimientoEstado.PENDIENTE: {
        SeguimientoAction.MARCAR_ENTREGADO: SeguimientoEstado.DOCUMENTO_ENTREGADO,
        SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO,
    },
    SeguimientoEstado.DOCUMENTO_ENTREGADO: {
        SeguimientoAction.ANEXAR: SeguimientoEstado.DOCUMENTO_ADJUNTO,
        SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO,
    },
    SeguimientoEstado.DOCUMENTO_ADJUNTO: {
        SeguimientoAction.COMPLETAR: SeguimientoEstado.SEGUIMIENTO_COMPLETADO,
    },
}


def _next_estado(
    current: SeguimientoEstado, action: SeguimientoAction
) -> SeguimientoEstado:
    """Return the next estado for a valid transition; raise ValueError if invalid."""
    next_states = _VALID_TRANSITIONS.get(current, {})
    next_estado = next_states.get(action)
    if next_estado is None:
        valid = ", ".join(a.value for a in next_states.keys()) or "none"
        raise ValueError(
            f"invalid transition: estado={current.value} action={action.value}, "
            f"valid actions from {current.value}: {valid}"
        )
    return next_estado


@dataclass(frozen=True, slots=True)
class SeguimientoTransitionResult:
    """Result of a successful seguimiento state transition."""
    adopcion_id: str
    estado_anterior: str
    nuevo_estado: str
    seguimiento_documento_entregado_at: str | None = None
    seguimiento_documento_url: str | None = None
    seguimiento_completado_at: str | None = None


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
    responsable_adopcion_id: str | None = None  # VOL-04 #37
    fecha_alta: str | None = None
    updated_at: str | None = None
    # ADOPT-03: seguimiento state machine fields
    seguimiento_estado: str | None = None
    seguimiento_documento_url: str | None = None
    seguimiento_documento_entregado_at: str | None = None
    seguimiento_completado_at: str | None = None

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
        responsable_adopcion_id=(
            str(row["responsable_adopcion_id"])
            if row.get("responsable_adopcion_id")
            else None
        ),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
        # ADOPT-03: seguimiento fields
        seguimiento_estado=row.get("seguimiento_estado"),
        seguimiento_documento_url=row.get("seguimiento_documento_url"),
        seguimiento_documento_entregado_at=(
            str(row["seguimiento_documento_entregado_at"])
            if row.get("seguimiento_documento_entregado_at")
            else None
        ),
        seguimiento_completado_at=(
            str(row["seguimiento_completado_at"])
            if row.get("seguimiento_completado_at")
            else None
        ),
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

    resp_id = _optional_text(params, "responsable_adopcion_id")
    if resp_id:
        sql, sql_params = queries.build_adopcion_check_responsable(resp_id)
        if not client.execute_sql(sql, sql_params):
            raise ValueError(
                "responsable_adopcion_id must reference an active volunteer"
            )

    raise ValueError(
        "FK validation failed (animal_id, voluntario_seguimiento, "
        "entrada, responsable_adopcion) — none matched"
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


# ---------------------------------------------------------------------------
# ADOPT-03: Seguimiento state machine (issue #49)
# ---------------------------------------------------------------------------


def transition_seguimiento(
    client: SqlExecutor,
    adopcion_id: str,
    action: SeguimientoAction,
    operador_user_id: str,
    documento_url: str | None = None,
) -> SeguimientoTransitionResult | None:
    """Transition the seguimiento estado for an adopcion.

    Validates the current estado against the action using the
    ``VALID_TRANSITIONS`` map. On success updates the row and returns
    ``SeguimientoTransitionResult`` with timestamps. On invalid transition
    raises ``ValueError``. When the adopcion is not found returns ``None``.

    Logs via ``log_safe`` per acceptance criterion 6.

    Raises:
        ValueError: the (estado, action) pair is not a valid transition.
        InsForgeError: transport errors propagate to the caller (route maps
            to 500).
    """
    # Fetch current adopcion to determine its estado
    current = get_adopcion_by_id(client, adopcion_id)
    if current is None:
        return None

    estado_anterior = current.seguimiento_estado or "PENDIENTE"
    try:
        current_estado = SeguimientoEstado(estado_anterior)
    except ValueError:
        # Treat unknown/None estado as PENDIENTE on first transition
        current_estado = SeguimientoEstado.PENDIENTE

    # Determine next estado; raises ValueError on invalid transition
    nuevo_estado = _next_estado(current_estado, action)

    # Build timestamp fields based on action
    now_ts = datetime.now(timezone.utc).isoformat()  # noqa: UP017
    entregado_at: str | None = None
    completado_at: str | None = None
    doc_url: str | None = None

    if action == SeguimientoAction.MARCAR_ENTREGADO:
        entregado_at = now_ts
    elif action == SeguimientoAction.ANEXAR:
        if documento_url is None:
            raise ValueError("documento_url is required for action ANEXAR")
        doc_url = documento_url
    elif action == SeguimientoAction.COMPLETAR:
        completado_at = now_ts

    sql, sql_params = queries.build_seguimiento_update(
        adopcion_id=adopcion_id,
        nuevo_estado=nuevo_estado.value,
        entregado_at=entregado_at,
        completado_at=completado_at,
        documento_url=doc_url,
    )
    rows = client.execute_sql(sql, sql_params)
    if not rows:
        return None

    result = SeguimientoTransitionResult(
        adopcion_id=adopcion_id,
        estado_anterior=estado_anterior,
        nuevo_estado=nuevo_estado.value,
        seguimiento_documento_entregado_at=(
            rows[0].get("seguimiento_documento_entregado_at")
        ),
        seguimiento_documento_url=rows[0].get("seguimiento_documento_url"),
        seguimiento_completado_at=(
            rows[0].get("seguimiento_completado_at")
        ),
    )

    log_safe(
        "adoption.seguimiento.transition",
        adopcion_id=adopcion_id,
        estado_anterior=estado_anterior,
        nuevo_estado=nuevo_estado.value,
        action=action.value,
        operador_user_id=operador_user_id,
    )

    return result
