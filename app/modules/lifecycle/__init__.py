"""Public API for the lifecycle slice (LIFECYCLE-03, PR-A + PR-B + PR-C).

The lifecycle slice owns the animal state cascade and its use cases.
Cross-module consumers (per AGENTS.md §27) MUST import from this
package surface (``app.modules.lifecycle``), never from the submodule
paths directly. The package surface carries:

- Domain types (:class:`DerivationKind`, :class:`DerivationResult`)
  and the pure cascade (:func:`calculate_state`).
- Application use cases:
  - :func:`calculate_animal_state` (PR-B).
  - :func:`persist_animal_state` (PR-B).
  - :func:`close_all_on_death` (PR-C).
  - :func:`close_previous_situation` (PR-C).
  - :func:`can_delete_animal` + :class:`CanDeleteResult` (PR-C).
"""
from app.modules.lifecycle.application.calculate_animal_state import (
    calculate_animal_state,
)
from app.modules.lifecycle.application.can_delete_animal import (
    CanDeleteResult,
    can_delete_animal,
)
from app.modules.lifecycle.application.close_all_on_death import (
    close_all_on_death,
)
from app.modules.lifecycle.application.close_previous_situation import (
    close_previous_situation,
)
from app.modules.lifecycle.application.persist_animal_state import (
    persist_animal_state,
)
from app.modules.lifecycle.di import build_lifecycle_port
from app.modules.lifecycle.domain.animal_state import (
    DerivationKind,
    DerivationResult,
    calculate_state,
)
from app.modules.lifecycle.domain.constants import STATE_INCOHERENTE
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort

__all__ = [
    "CanDeleteResult",
    "DerivationKind",
    "DerivationResult",
    "LifecyclePort",
    "STATE_INCOHERENTE",
    "build_lifecycle_port",
    "calculate_animal_state",
    "calculate_state",
    "can_delete_animal",
    "close_all_on_death",
    "close_previous_situation",
    "persist_animal_state",
]
