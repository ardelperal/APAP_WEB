"""Port for the lifecycle slice (LIFECYCLE-03, PR-A work-unit A4).

The port is the contract between the use cases (``application/`` in
PR-B) and the adapters (InsForge in PR-B, Access via the legacy
adapter when it lands). The Protocol depends on
``app.core.data_access.SqlExecutor`` — never on ``InsForgeClient``
(AGENTS.md §31).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.domain.animal_state import DerivationResult


@runtime_checkable
class LifecyclePort(Protocol):
    """Port that hides the transport behind a domain-typed surface.

    Implementations are responsible for (1) loading the active
    placements from the source-of-truth tables, (2) calling
    :func:`app.modules.lifecycle.domain.animal_state.calculate_state`,
    (3) persisting the resulting ``DerivationResult`` to the cache
    table (and, when the event log is the authoritative source,
    appending the corresponding lifecycle event first). No
    implementation lives here — only the contract.
    """

    def calculate_state(self, animal_id: str) -> DerivationResult:
        """Return the current ``DerivationResult`` for ``animal_id``."""
        ...

    def persist_animal_state(
        self, animal_id: str, result: DerivationResult
    ) -> None:
        """Upsert the ``animal_current_state`` row for ``animal_id``."""
        ...


PORT_REQUIRES_SQL_EXECUTOR: tuple[type[Any], ...] = (SqlExecutor,)


__all__ = ["LifecyclePort", "PORT_REQUIRES_SQL_EXECUTOR"]
