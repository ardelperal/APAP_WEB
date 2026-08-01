"""Rule engine for the task engine (issue #7).

Pure functions that inspect domain state and return task drafts.
No side effects — rules only return lists of TareaDraft dataclasses.

The scheduler (``scheduler.py``) runs all registered rules and persists
the drafts. For the first MVC this is a manual CLI command.

Rule registry:
  TASK_RULES: dict[RuleName, Callable[[Context], list[TareaDraft]]]

Context shape (per rule):
  - rule_vacuna_vencimiento: {"vacunas": [{"animal_id", "vacuna_tipo", "fecha_vencimiento"}]}
  - rule_seguimiento_post_adopcion: {"adopciones": [...], "seguimientos": [...]}
  - rule_esterilizacion_pendiente: {"animales": [...], "esterilizaciones": [...]}
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

# --- draft ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TareaDraft:
    """A pre-persistence task draft returned by a rule.

    The scheduler converts this into a crear_tarea call.
    """

    tipo: str
    origen: str
    prioridad: str
    vencimiento_at: str | None = None
    vinculo_tipo: str | None = None
    vinculo_id: str | None = None
    metadata: dict[str, Any] | None = None


# --- context types --------------------------------------------------------


# Minimal context type aliases for documentation clarity.
Context = dict[str, Any]
RuleName = str

# --- registry -------------------------------------------------------------


TASK_RULES: Final[dict[RuleName, Callable[[Context], list[TareaDraft]]]] = {}


def _register_rule(name: RuleName) -> Callable[[Callable[[Context], list[TareaDraft]]], Callable[[Context], list[TareaDraft]]]:
    """Decorator to register a rule in TASK_RULES."""

    def decorator(func: Callable[[Context], list[TareaDraft]]) -> Callable[[Context], list[TareaDraft]]:
        TASK_RULES[name] = func
        return func

    return decorator


# --- rule: vaccine expiration ---------------------------------------------


@_register_rule("vacuna_vencimiento")
def rule_vacuna_vencimiento(ctx: Context) -> list[TareaDraft]:
    """Draft tareas for animals with vaccines expiring in <7 days.

    Context keys:
      vacunas: list of dicts with keys animal_id, vacuna_tipo, fecha_vencimiento (ISO str)
    """
    vacunas: list[dict] = ctx.get("vacunas", [])
    drafts: list[TareaDraft] = []
    threshold = date.today() + timedelta(days=7)

    for vacuna in vacunas:
        vencimiento_str = vacuna.get("fecha_vencimiento")
        if not vencimiento_str:
            continue
        try:
            vencimiento = date.fromisoformat(vencimiento_str)
        except ValueError:
            continue

        if vencimiento <= threshold:
            drafts.append(
                TareaDraft(
                    tipo="automatica_vacuna",
                    origen="regla_salud",
                    prioridad="alta",
                    vencimiento_at=vencimiento_str,
                    vinculo_tipo="animal",
                    vinculo_id=vacuna.get("animal_id"),
                    metadata={
                        "vacuna_tipo": vacuna.get("vacuna_tipo"),
                        "dias_hasta_vencimiento": (vencimiento - date.today()).days,
                    },
                )
            )
    return drafts


# --- rule: post-adoption follow-up ---------------------------------------


@_register_rule("seguimiento_post_adopcion")
def rule_seguimiento_post_adopcion(ctx: Context) -> list[TareaDraft]:
    """Draft tareas for adoptions >30 days old without a follow-up recorded.

    Context keys:
      adopciones: list of dicts with keys id, animal_id, fecha_adopcion (ISO str)
      seguimientos: list of dicts with keys adopcion_id, fecha (ISO str)
    """
    adopciones: list[dict] = ctx.get("adopciones", [])
    seguimientos: list[dict] = ctx.get("seguimientos", [])
    threshold_days = 30

    # Build a set of adopcion_ids that have a follow-up after the threshold
    followed_adopcion_ids: set[str] = set()
    for seg in seguimientos:
        seg_fecha_str = seg.get("fecha")
        if not seg_fecha_str:
            continue
        try:
            date.fromisoformat(seg_fecha_str)
        except ValueError:
            continue
        # Only count follow-ups that are meaningful (not extremely recent ones)
        if seg.get("adopcion_id"):
            followed_adopcion_ids.add(seg["adopcion_id"])

    drafts: list[TareaDraft] = []
    for adopcion in adopciones:
        fecha_adopcion_str = adopcion.get("fecha_adopcion")
        if not fecha_adopcion_str:
            continue
        try:
            fecha_adopcion = date.fromisoformat(fecha_adopcion_str)
        except ValueError:
            continue

        days_since = (date.today() - fecha_adopcion).days
        if days_since >= threshold_days and adopcion["id"] not in followed_adopcion_ids:
            drafts.append(
                TareaDraft(
                    tipo="automatica_seguimiento_post_adopcion",
                    origen="regla_adopcion",
                    prioridad="normal",
                    vinculo_tipo="adopcion",
                    vinculo_id=adopcion.get("id"),
                    metadata={
                        "animal_id": adopcion.get("animal_id"),
                        "dias_desde_adopcion": days_since,
                    },
                )
            )
    return drafts


# --- rule: sterilization pending ------------------------------------------


@_register_rule("esterilizacion_pendiente")
def rule_esterilizacion_pendiente(ctx: Context) -> list[TareaDraft]:
    """Draft tareas for animals >1 year old without sterilization record.

    Only applies to animals with sexo = 'macho' or 'hembra' (any non-unknown).
    Animals with sterilization records are excluded.

    Context keys:
      animales: list of dicts with keys id, fecha_nacimiento (ISO str), sexo
      esterilizaciones: list of dicts with keys animal_id, fecha (ISO str)
    """
    animales: list[dict] = ctx.get("animales", [])
    esterilizaciones: list[dict] = ctx.get("esterilizaciones", [])
    threshold_years = 1

    # Build set of animal_ids that have been sterilized
    sterilized_ids: set[str] = {e["animal_id"] for e in esterilizaciones if e.get("animal_id")}

    drafts: list[TareaDraft] = []
    for animal in animales:
        fnac_str = animal.get("fecha_nacimiento")
        if not fnac_str:
            continue
        try:
            fnac = date.fromisoformat(fnac_str)
        except ValueError:
            continue

        # Skip if younger than threshold
        age_years = (date.today() - fnac).days / 365.25
        if age_years < threshold_years:
            continue

        # Skip already sterilized
        if animal["id"] in sterilized_ids:
            continue

        # Only apply to known-sex animals (both sexes need sterilization)
        sexo = animal.get("sexo", "").lower()
        if sexo not in ("macho", "hembra"):
            continue

        drafts.append(
            TareaDraft(
                tipo="automatica_esterilizacion",
                origen="regla_salud",
                prioridad="normal",
                vinculo_tipo="animal",
                vinculo_id=animal.get("id"),
                metadata={
                    "sexo": sexo,
                    "edad_anos": round(age_years, 1),
                },
            )
        )
    return drafts
