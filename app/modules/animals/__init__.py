"""Animals feature module: routes for the basic CRUD (list, create, get, update, delete).

Public API per AGENTS.md §27 — cross-module consumers import from this
package surface (``app.modules.animals``), never from the submodule
paths directly. The module currently exports:

- :func:`get_animal_by_id` (hexagonal primary-key lookup, FOSTER-03 +
  ``foster/assignment.py`` consumer).
- :func:`validate_lifecycle_causal_pair` — the LIFECYCLE-02 (issue #32)
  service-layer entrypoint that enforces the D-23 causal-pair rule on
  lifecycle events. The actual event recorder (``record_event``) lives
  in :mod:`app.modules.animals.lifecycle_events` and must be imported
  from there directly — it is no longer re-exported through this
  package surface (see AGENTS.md §27 public-API rule). Routes that
  emit lifecycle events still go through that recorder rather than
  writing SQL themselves (AGENTS.md §1 + §22).
- :func:`calculate_animal_state` + :func:`persist_animal_state` +
  :func:`close_all_on_death` + :func:`close_previous_situation` +
  :func:`can_delete_animal` — the LIFECYCLE-03 (issue #33) lifecycle
  use cases that compose the domain cascade (PR-A + PR-B) with the
  close/can_delete primitives added in PR-C. Re-exported here so
  consumers can route through ``app.modules.animals`` without
  importing the slice's internal submodules directly
  (AGENTS.md §27 public-API rule).
"""

from app.modules.animals.application.get_animal_by_id import get_animal_by_id
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.lifecycle_events import (
    CORE_EVENT_TYPES,
    SUPPORTING_EVENT_TYPES,
    CausalPairViolation,
    LifecycleEventType,
)
from app.modules.animals.lifecycle_events import (
    validate_causal_pair as validate_lifecycle_causal_pair,
)
from app.modules.animals.ports.animals_port import AnimalsPort
from app.modules.lifecycle import (
    CanDeleteResult,
    calculate_animal_state,
    can_delete_animal,
    close_all_on_death,
    close_previous_situation,
    persist_animal_state,
)

__all__ = [
    "CORE_EVENT_TYPES",
    "AnimalsPort",
    "CanDeleteResult",
    "CausalPairViolation",
    "LifecycleEventType",
    "SUPPORTING_EVENT_TYPES",
    "calculate_animal_state",
    "can_delete_animal",
    "close_all_on_death",
    "close_previous_situation",
    "get_animal_by_id",
    "get_animals_port",
    "persist_animal_state",
    "validate_lifecycle_causal_pair",
]
