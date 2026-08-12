"""Animals feature module: routes for the basic CRUD (list, create, get, update, delete).

Public API per AGENTS.md §27 — cross-module consumers import from this
package surface (``app.modules.animals``), never from the submodule
paths directly. The module currently exports:

- :func:`get_animal_by_id` (legacy CRUD contract, FOSTER-03 +
  ``foster/assignment.py`` consumer).
- :func:`record_lifecycle_event` + :func:`validate_lifecycle_causal_pair`
  — the LIFECYCLE-02 (issue #32) service-layer entrypoints for the
  animal lifecycle event log + the D-23 causal-pair rule. Routes that
  emit lifecycle events will go through these rather than writing SQL
  directly (AGENTS.md §1 + §22).
- :func:`calculate_animal_state` + :func:`persist_animal_state` +
  :func:`close_all_on_death` + :func:`close_previous_situation` +
  :func:`can_delete_animal` — the LIFECYCLE-03 (issue #33) lifecycle
  use cases that compose the domain cascade (PR-A + PR-B) with the
  close/can_delete primitives added in PR-C. Re-exported here so
  consumers can route through ``app.modules.animals`` without
  importing the slice's internal submodules directly
  (AGENTS.md §27 public-API rule).
"""

from app.modules.animals.lifecycle_events import (
    CORE_EVENT_TYPES,
    SUPPORTING_EVENT_TYPES,
    CausalPairViolation,
    LifecycleEventType,
)
from app.modules.animals.lifecycle_events import (
    record_event as record_lifecycle_event,
)
from app.modules.animals.lifecycle_events import (
    validate_causal_pair as validate_lifecycle_causal_pair,
)
from app.modules.animals.service import get_animal_by_id
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
    "CanDeleteResult",
    "CausalPairViolation",
    "LifecycleEventType",
    "SUPPORTING_EVENT_TYPES",
    "calculate_animal_state",
    "can_delete_animal",
    "close_all_on_death",
    "close_previous_situation",
    "get_animal_by_id",
    "persist_animal_state",
    "record_lifecycle_event",
    "validate_lifecycle_causal_pair",
]
