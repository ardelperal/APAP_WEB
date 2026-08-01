"""Rule engine for the common task engine (issue #7).

Rule engine structure:
  TASK_RULES: list of (rule_name, callable) tuples.
  Each callable: def rule_name(context: dict) -> list[TareaDraft].

This module is intentionally simple at MVP. The three stubs below
cover the three highest-priority automatic task types identified in
the issue discovery scope:

  1. rule_vacuna_vencimiento       — vaccines expiring in <7 days
  2. rule_seguimiento_post_adopcion — adoptions >30 days without follow-up
  3. rule_esterilizacion_pendiente — animals >1 year without sterilization

The actual rule implementation is deferred to the first MVC.
The rule engine does NOT write to the database — it returns drafts
that the caller (a scheduled job or manual trigger) can persist.

Context shape accepted by all rules:
  {
      "vacunas":          list[dict]  — see rule_vacuna_vencimiento
      "adopciones":       list[dict]  — see rule_seguimiento_post_adopcion
      "seguimientos":     list[dict]  — post-adoption follow-ups
      "animales":         list[dict]  — see rule_esterilizacion_pendiente
      "esterilizaciones": list[dict]  — sterilization records
  }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# --- draft -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TareaDraft:
    """A pre-validated tarea before insertion.

    Produced by rule functions; consumed by the task-engine service.
    All fields are primitive types or None — no domain objects.
    """

    tipo: str
    origen: str
    prioridad: str
    vinculo_tipo: str
    vinculo_id: str
    metadata: dict[str, Any] | None = None
    vencimiento_at: str | None = None


# --- helpers ---------------------------------------------------------------


def _days_until(iso_date: str) -> int:
    """Return signed days from today to the given ISO date string."""
    target = date.fromisoformat(iso_date)
    return (target - date.today()).days


# --- rules -----------------------------------------------------------------


def rule_vacuna_vencimiento(context: dict) -> list[TareaDraft]:
    """Draft tareas for animals with vaccines expiring in <7 days.

    Context keys used:
      vacunas — list of dicts with keys:
        - animal_id:  str
        - vacuna_tipo: str
        - fecha_vencimiento: ISO date string

    Returns one draft per vaccine expiring in <7 days, prioridad=alta.
    """
    vacunas: list[dict] = context.get("vacunas", [])
    drafts: list[TareaDraft] = []
    for vac in vacunas:
        try:
            days = _days_until(vac["fecha_vencimiento"])
        except (KeyError, ValueError):
            continue
        if 0 <= days < 7:
            drafts.append(
                TareaDraft(
                    tipo="automatica_vacuna",
                    origen="regla_salud",
                    prioridad="alta",
                    vinculo_tipo="animal",
                    vinculo_id=vac["animal_id"],
                    metadata={"vacuna_tipo": vac.get("vacuna_tipo"), "dias_hasta_vencimiento": days},
                    vencimiento_at=vac["fecha_vencimiento"],
                )
            )
    return drafts


def rule_seguimiento_post_adopcion(context: dict) -> list[TareaDraft]:
    """Draft tareas for adoptions >30 days old without a follow-up.

    Context keys used:
      adopciones — list of dicts with keys:
        - id:        str  (adopcion UUID)
        - animal_id: str
        - fecha_adopcion: ISO date string
      seguimientos — list of dicts with keys:
        - adopcion_id: str
        - fecha: ISO date string

    Returns one draft per adoption >30 days old without any follow-up
    recorded after the adoption date.
    """
    adopciones: list[dict] = context.get("adopciones", [])
    seguimientos: list[dict] = context.get("seguimientos", [])

    # Build a set of adopcion_ids that have a follow-up after adoption
    followed: set[str] = set()
    for seg in seguimientos:
        try:
            ad_id = seg["adopcion_id"]
            seg_date = date.fromisoformat(seg["fecha"])
            for adop in adopciones:
                if adop["id"] == ad_id:
                    adop_date = date.fromisoformat(adop["fecha_adopcion"])
                    if seg_date > adop_date:
                        followed.add(ad_id)
                    break
        except (KeyError, ValueError):
            continue

    drafts: list[TareaDraft] = []
    for adop in adopciones:
        try:
            days_since = abs(_days_until(adop["fecha_adopcion"]))
        except (KeyError, ValueError):
            continue
        if days_since <= 30 and adop["id"] not in followed:
            continue
        if adop["id"] not in followed:
            drafts.append(
                TareaDraft(
                    tipo="automatica_seguimiento_post_adopcion",
                    origen="regla_adopcion",
                    prioridad="normal",
                    vinculo_tipo="adopcion",
                    vinculo_id=adop["id"],
                    metadata={"animal_id": adop.get("animal_id")},
                )
            )
    return drafts


def rule_esterilizacion_pendiente(context: dict) -> list[TareaDraft]:
    """Draft tareas for intact male animals >1 year old without a sterilization.

    Context keys used:
      animales — list of dicts with keys:
        - id: str
        - fecha_nacimiento: ISO date string
        - sexo: str  — "macho" | "hembra"
      esterilizaciones — list of dicts with keys:
        - animal_id: str
        - fecha: ISO date string

    Returns one draft per male animal born >1 year ago with no
    sterilization record.
    """
    animales: list[dict] = context.get("animales", [])
    esterilizaciones: list[dict] = context.get("esterilizaciones", [])

    sterilized: set[str] = {e["animal_id"] for e in esterilizaciones}

    drafts: list[TareaDraft] = []
    for animal in animales:
        if animal.get("sexo") != "macho":
            continue
        try:
            birth = date.fromisoformat(animal["fecha_nacimiento"])
            age_days = (date.today() - birth).days
        except (KeyError, ValueError):
            continue
        if age_days > 365 and animal["id"] not in sterilized:
            drafts.append(
                TareaDraft(
                    tipo="automatica_esterilizacion",
                    origen="regla_salud",
                    prioridad="normal",
                    vinculo_tipo="animal",
                    vinculo_id=animal["id"],
                    metadata={"sexo": animal.get("sexo")},
                )
            )
    return drafts


# --- registry --------------------------------------------------------------
# TASK_RULES is placed AFTER all function definitions so that forward
# references resolve correctly at module load time.

TASK_RULES: list[tuple[str, Any]] = [
    ("rule_vacuna_vencimiento", rule_vacuna_vencimiento),
    ("rule_seguimiento_post_adopcion", rule_seguimiento_post_adopcion),
    ("rule_esterilizacion_pendiente", rule_esterilizacion_pendiente),
]
