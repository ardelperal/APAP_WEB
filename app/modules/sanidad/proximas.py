"""Proximity-report service for HEALTH-05 sanidad (issue #652).

Owns the ``ProximaPrueba`` domain type, the ``vencida/proxima/futura``
state derivation, and the SQL round-trip that produces one row per
(animal, tipo_prueba) combination whose next due date falls inside the
operator's window.

Extracted from ``app.modules.sanidad.service`` so the parent service
module stays under the 700-line budget (AGENTS.md rule 21). The split
follows the proximity-report domain boundary: ``service.py`` keeps the
CRUD over ``actuacion_sanitaria``; this module owns the read-only
projection that the dashboard and the operator's triage report consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.core.data_access import SqlExecutor
from app.modules.sanidad import queries


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
        client: the SqlExecutor (production ``AuthUsersPort`` or the
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


def serialize_proximas_pruebas(items: list[ProximaPrueba]) -> list[dict[str, Any]]:
    """Project a list of ``ProximaPrueba`` rows to the JSON payload shape.

    Lives next to the domain type so the route handler stays HTTP-only
    (AGENTS.md rule 28: keep handlers under 50 lines and move the
    HTTP-unrelated logic to the service layer).
    """
    return [
        {
            "chip": item.chip,
            "nombre": item.nombre,
            "tipo_codigo": item.tipo_codigo,
            "fecha_ultima": item.fecha_ultima.isoformat(),
            "fecha_proxima": item.fecha_proxima.isoformat(),
            "periodicidad_meses": item.periodicidad_meses,
            "estado": item.estado,
        }
        for item in items
    ]
