"""Application layer for the lifecycle slice (LIFECYCLE-03, PR-B).

Use cases live as one-function-per-file modules (AGENTS.md §33.3)
so each use case is independently testable and a future split into
separate handler modules does not require splitting a god-file.

Public surface:

- :func:`app.modules.lifecycle.application.calculate_animal_state.calculate_animal_state`
- :func:`app.modules.lifecycle.application.persist_animal_state.persist_animal_state`

The close + can_delete use cases land in PR-C.
"""
from __future__ import annotations

from app.modules.lifecycle.application.calculate_animal_state import (
    calculate_animal_state,
)
from app.modules.lifecycle.application.persist_animal_state import (
    persist_animal_state,
)

__all__ = ["calculate_animal_state", "persist_animal_state"]
