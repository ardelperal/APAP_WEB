"""Periodicity engine for health actuations (HEALTH-05, #54).

Computes the next due date for a recurring health test and creates a
pending ``tarea`` when an ``actuacion_sanitaria`` is registered.

The engine has two entry points:

1. **Inline** — called from ``create_actuacion_sanitaria``: after the
   actuation is committed, this module looks up the periodicity rule for
   (tipo_actuacion.codigo, animal.especie), computes the next due date,
   and creates a linked ``tarea``. One-shot tests
   (``periodicidad_meses IS NULL``) produce no task.

2. **Batch scan** — ``scan_and_generate_pending_tasks``: finds every
   (animal, test_type) combination where the next due date has passed
   but no pending ``tarea`` exists, and creates the missing tasks.
   Run on schedule or on-demand from the admin panel.

The periodicity catalog (``catalogos_periodicidad``) uses (codigo, especie)
as the natural key. ``especie = NULL`` means "applies to all species".
The lookup uses the most-specific match: exact (codigo, especie) first,
then wildcard (codigo, NULL).

Mapping codigo → TipoTarea::

    "Vacuna Polivalente"          → AUTOMATICA_VACUNA
    "Rabia"                      → AUTOMATICA_VACUNA
    "Desparasitación Interna"     → AUTOMATICA_DESPARASITACION
    "Desparasitación Externa"     → AUTOMATICA_DESPARASITACION
    "Leishmaniosis"              → AUTOMATICA_TRATAMIENTO
    (anything else with meses>0)  → AUTOMATICA_TRATAMIENTO
    (periodicidad_meses IS NULL)  → no task (one-shot, e.g. Esterilización)

The engine owns no SQL strings directly. It calls:
- ``app.core.catalogs.list_catalogos_periodicidad`` for the catalog read.
- ``app.modules.tasks.service.crear_tarea`` for task creation.
- The caller passes the ``AnimalsPort`` so this module stays adapter-agnostic.

Framework-agnostic: no FastAPI, no LocalBackend, no SQL here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# --- lookup helpers -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodicidadRule:
    """A row from ``catalogos_periodicidad`` relevant to one actuation."""

    codigo: str  # matches catalogos_pruebas.codigo
    especie: str | None  # NULL = applies to all
    periodicidad_meses: int | None  # NULL = one-shot (Esterilización)
    nombre: str | None = None
    orden: int | None = None

    def is_recurring(self) -> bool:
        """True when this test has a recurring interval (not one-shot)."""
        return self.periodicidad_meses is not None and self.periodicidad_meses > 0

    def next_due_date(self, last_actuacion_date: date) -> date:
        """Compute the next due date from the last actuation date.

        Adds ``periodicidad_meses`` months to ``last_actuacion_date``.
        Raises ``ValueError`` if ``periodicidad_meses`` is not positive
        (use ``is_recurring()`` to guard before calling).
        """
        if not self.is_recurring():
            raise ValueError(
                f"next_due_date called on a one-shot rule "
                f"(periodicidad_meses={self.periodicidad_meses!r})"
            )
        # ``dateutil.relativedelta`` handles month overflow correctly
        # (e.g. Jan 31 + 1 month → Feb 28/29, not Mar 2/3).
        assert self.periodicidad_meses is not None  # guarded by is_recurring()
        try:
            # lazy-import: optional dependency with a deterministic fallback.
            from dateutil.relativedelta import (
                relativedelta,
            )
        except ImportError:  # pragma: no cover
            # Fallback for environments without dateutil: manual month arithmetic.
            return _fallback_add_months(last_actuacion_date, self.periodicidad_meses)

        return last_actuacion_date + relativedelta(months=self.periodicidad_meses)


def _fallback_add_months(d: date, months: int) -> date:
    """Fallback month arithmetic without dateutil.

    Handles year rollover but does NOT handle day-overflow correctly
    (Jan 31 + 1 month → Mar 2/3 instead of Feb 28). Use dateutil in
    production.
    """
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given year+month."""
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


# --- TipoTarea mapping ----------------------------------------------------


def codigo_to_tipo_tarea(codigo: str) -> str:
    """Map a ``catalogos_periodicidad.codigo`` to a ``TipoTarea`` value.

    Mirrors the hard-coded mapping documented in the module docstring.
    Extensible: add a new branch before the fallback for a new test type.
    """
    upper = codigo.upper()
    if "VACUNA" in upper or "RABIA" in upper:
        return "automatica_vacuna"
    if "DESPARASIT" in upper:
        return "automatica_desparasitacion"
    return "automatica_tratamiento"


# --- periodicity rule lookup -----------------------------------------------


def find_periodicity_rule(
    catalogos_periodicidad: list[dict[str, Any]],
    codigo: str,
    especie: str | None,
) -> PeriodicidadRule | None:
    """Find the most-specific periodicity rule for a (codigo, especie) pair.

    Priority: exact (codigo, especie) match first, then wildcard
    (codigo, NULL). Returns None when no rule exists — the test is not
    configured for scheduling.
    """
    # Normalise especie for comparison.
    especie_key = especie.upper() if especie else None

    # Pass 1: exact (codigo, especie) match.
    for row in catalogos_periodicidad:
        if row.get("codigo") == codigo and (
            (row.get("especie") or "").upper() == especie_key if especie_key
            else row.get("especie") is None
        ):
            return PeriodicidadRule(
                codigo=str(row["codigo"]),
                especie=row.get("especie"),
                periodicidad_meses=row.get("periodicidad_meses"),
                nombre=row.get("nombre"),
                orden=row.get("orden"),
            )

    # Pass 2: wildcard (codigo, NULL) — applies to all species.
    for row in catalogos_periodicidad:
        if row.get("codigo") == codigo and row.get("especie") is None:
            return PeriodicidadRule(
                codigo=str(row["codigo"]),
                especie=None,
                periodicidad_meses=row.get("periodicidad_meses"),
                nombre=row.get("nombre"),
                orden=row.get("orden"),
            )

    return None


# --- main engine functions -----------------------------------------------


def generate_next_tarea(
    *,
    last_actuacion_date: date,
    periodicidad_rule: PeriodicidadRule,
    animal_id: str,
    actuacion_id: str,
) -> dict[str, Any] | None:
    """Build the dict for ``tareas_service.crear_tarea`` from a periodicity rule.

    Returns a task-creation param dict, or ``None`` when the test is one-shot
    (``periodicidad_meses IS NULL``). The ``tareas_service.crear_tarea``
    call is the caller's responsibility so this function stays transport-agnostic.

    The task is linked to the actuation via ``vinculo_tipo="actuacion_sanitaria"``
    and ``vinculo_id=actuacion_id`` so closing the task can optionally update
    the actuation record (future work).

    The ``metadata`` carries the periodicity context for debugging and for
    the future "mark as done → create next task" chain.
    """
    if not periodicidad_rule.is_recurring():
        return None

    next_date = periodicidad_rule.next_due_date(last_actuacion_date)
    next_date_iso = next_date.isoformat()

    return {
        "tipo": codigo_to_tipo_tarea(periodicidad_rule.codigo),
        "origen": "regla_salud",
        "prioridad": _priority_from_date(next_date),
        "vencimiento_at": next_date_iso,
        "vinculo_tipo": "actuacion_sanitaria",
        "vinculo_id": actuacion_id,
        "metadata": {
            "codigo_prueba": periodicidad_rule.codigo,
            "periodicidad_meses": periodicidad_rule.periodicidad_meses,
            "animal_id": animal_id,
            "actuacion_id": actuacion_id,
            "last_actuacion_date": last_actuacion_date.isoformat(),
            "next_due_date": next_date_iso,
        },
    }


def _priority_from_date(due_date: date) -> str:
    """Assign a business priority based on how overdue the task is."""
    today = date.today()
    days_overdue = (today - due_date).days
    if days_overdue > 30:
        return "urgente"
    if days_overdue > 7:
        return "alta"
    if days_overdue > 0:
        return "normal"
    return "baja"
