"""``persist_animal_state`` use case (LIFECYCLE-03 PR-B).

Thin orchestration: hand ``animal_id`` + ``DerivationResult`` to
the injected
:class:`~app.modules.lifecycle.ports.lifecycle_port.LifecyclePort`
and let the adapter upsert the cache row. No transport imports,
no SQL -- the use case depends only on the Protocol defined in
:mod:`app.modules.lifecycle.ports.lifecycle_port` (AGENTS.md §31,
§33.4).

Callers in PR-C (the close + can_delete + rewrite of
``app.modules.animals.lifecycle_events.py``) will reach this use
case through ``app.modules.lifecycle.di.get_lifecycle_port``.
"""
from __future__ import annotations

from app.modules.lifecycle.domain.animal_state import DerivationResult
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


def persist_animal_state(
    port: LifecyclePort, animal_id: str, result: DerivationResult
) -> None:
    """Upsert the ``animal_current_state`` cache row for ``animal_id``.

    The use case is intentionally a one-liner: the cache schema
    lives in :mod:`app.core.domain_lifecycle` (DDL only) and the
    SQL lives in the adapter (AGENTS.md §22). The use case is the
    seam that ties them together; future PRs that need to write
    auxiliary columns (``pre_death_state``, ``active_intake_id``,
    etc.) extend the adapter -- not this use case.
    """
    port.persist_animal_state(animal_id, result)


__all__ = ["persist_animal_state"]
