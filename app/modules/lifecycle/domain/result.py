"""Output dataclass for the lifecycle state cascade.

Lives in its own module so ``animal_state.py`` stays under the
mutation-sites budget (AGENTS.md §21 / ``scripts/check_mutation_sites.py``).
Pure data — no logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DerivationResult:
    """Output of ``calculate_state``.

    ``state`` is the CHECK-enforced string written to
    ``animal_current_state.current_state``. ``pre_death_state`` is set
    only when ``kind`` is ``FALLECIDO`` (one of Albergue/Acogida/
    Adoptado/Entregado or Desconocido). ``active_*_id`` carry the
    legacy PK of the placement that produced the active state; all
    three are ``None`` for terminal states and Incoherente.
    """

    state: str
    kind: object  # DerivationKind — imported at use site to avoid cycles
    pre_death_state: str | None = None
    active_intake_id: str | None = None
    active_foster_id: str | None = None
    active_adoption_id: str | None = None


__all__ = ["DerivationResult"]
