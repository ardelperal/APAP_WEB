"""Domain-level state string constants for the lifecycle cascade.

Centralizes the 13 ``STATE_*`` string literals that drive the 6-level
priority cascade (AGENTS.md §4: one source of truth per domain concept).
Pure data — no logic, no I/O.

The accented spelling ``Pendiente de Nueva Situación`` (with acute) is the
canonical form enforced by the ``animal_current_state.current_state``
CHECK constraint and the cascade output. The non-accented variant lives
only inside legacy Access/VBA importers and must never appear in web
output.
"""

from __future__ import annotations

STATE_PENDIENTE_ENTRADA = "Pendiente de Entrada"
STATE_PENDIENTE_NUEVA_SITUACION = "Pendiente de Nueva Situación"
STATE_ALBERGUE = "Albergue"
STATE_ACOGIDA = "Acogida"
STATE_ADOPTADO = "Adoptado"
STATE_ENTREGADO = "Entregado"
STATE_INCOHERENTE = "Incoherente"
STATE_FALLECIDO_ALBERGUE = "Fallecido (Albergue)"
STATE_FALLECIDO_ACOGIDA = "Fallecido (Acogida)"
STATE_FALLECIDO_ADOPTADO = "Fallecido (Adoptado)"
STATE_FALLECIDO_ENTREGADO = "Fallecido (Entregado)"
STATE_FALLECIDO_DESCONOCIDO = "Fallecido (Desconocido)"

#: States that may appear as the parenthetical of a ``Fallecido ({pre})`` value.
#: Anything outside this set falls back to PRE_DEATH_STATE_DESCONOCIDO.
_VALID_PRE_DEATH_STATES: frozenset[str] = frozenset(
    {STATE_ALBERGUE, STATE_ACOGIDA, STATE_ADOPTADO, STATE_ENTREGADO}
)
PRE_DEATH_STATE_DESCONOCIDO = "Desconocido"


__all__ = [
    "PRE_DEATH_STATE_DESCONOCIDO",
    "STATE_ACOGIDA",
    "STATE_ADOPTADO",
    "STATE_ALBERGUE",
    "STATE_ENTREGADO",
    "STATE_FALLECIDO_ACOGIDA",
    "STATE_FALLECIDO_ADOPTADO",
    "STATE_FALLECIDO_ALBERGUE",
    "STATE_FALLECIDO_DESCONOCIDO",
    "STATE_FALLECIDO_ENTREGADO",
    "STATE_INCOHERENTE",
    "STATE_PENDIENTE_ENTRADA",
    "STATE_PENDIENTE_NUEVA_SITUACION",
    "_VALID_PRE_DEATH_STATES",
]
