"""``calculate_animal_state`` use case (LIFECYCLE-03 PR-B).

Thin orchestration: hand ``animal_id`` to the injected
:class:`~app.modules.lifecycle.ports.lifecycle_port.LifecyclePort`
and return the resulting :class:`DerivationResult`. No transport
imports, no SQL -- the use case depends only on the Protocol
defined in :mod:`app.modules.lifecycle.ports.lifecycle_port`
(AGENTS.md §31, §33.4).

Callers in PR-C (the close + can_delete + rewrite of
``app.modules.animals.lifecycle_events.py``) will reach this use
case through ``app.modules.lifecycle.di.get_lifecycle_port``.
"""
from __future__ import annotations

from app.modules.lifecycle.domain.animal_state import DerivationResult
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


def calculate_animal_state(
    port: LifecyclePort, animal_id: str
) -> DerivationResult:
    """Return the current ``DerivationResult`` for ``animal_id``.

    The use case is intentionally a one-liner: the cascade lives
    in the domain (AGENTS.md §33.4 -- application is
    transport-agnostic) and the SQL lives in the adapter
    (AGENTS.md §22 -- SQL builders return tuples). The use case
    is the seam that ties them together.
    """
    return port.calculate_state(animal_id)


__all__ = ["calculate_animal_state"]
