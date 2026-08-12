"""InsForge adapter implementing :class:`LifecyclePort`.

The adapter is the only module in the lifecycle slice that talks
to the InsForge transport (via the
:class:`~app.core.data_access.SqlExecutor` Protocol -- the
backend-agnostic contract introduced in issue #259). The SQL
lives in :mod:`app.modules.lifecycle.adapters.insforge.lifecycle_insforge_queries`
per AGENTS.md §22; this module is pure orchestration: load the
ficha + the three active-collection projections, hand the rows to
the domain cascade (:func:`app.modules.lifecycle.domain.animal_state.calculate_state`),
and either return the ``DerivationResult`` or upsert it to the
cache table.

The adapter is a thin, stateless object -- instantiation is cheap
(no I/O, no connection). The DI provider in
:mod:`app.modules.lifecycle.di.lifecycle_di` constructs one per
request from the pooled
:class:`~app.core.insforge.InsForgeClient` that the application
lifespan already owns.

LIFECYCLE-03 (issue #33) PR-B.
"""
from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.adapters.insforge import lifecycle_insforge_queries as q
from app.modules.lifecycle.domain.animal_state import (
    DerivationResult,
    calculate_state,
)


class InsForgeLifecycleAdapter:
    """InsForge implementation of :class:`LifecyclePort`.

    The adapter is constructed per request by the DI provider. It
    holds only the executor (no mutable state) so it is safe to
    share across the request lifetime.

    Implements the two-method protocol defined in
    ``app/modules/lifecycle/ports/lifecycle_port.py``: read the
    cascade inputs (ficha + 3 active collections) and either
    return the derived :class:`DerivationResult` or write it back
    to ``animal_current_state``.
    """

    def __init__(self, executor: SqlExecutor) -> None:
        self._executor = executor

    def calculate_state(self, animal_id: str) -> DerivationResult:
        """Read the cascade inputs from the source-of-truth tables.

        Issues four SELECTs (one per builder) and feeds the rows
        to the domain :func:`calculate_state`. The domain function
        is pure -- no I/O -- so the adapter is responsible for the
        ``ficha=None`` vs ``ficha=row[0]`` translation: an empty
        ficha list means "no row in animales" and is passed as
        ``None`` so the cascade falls through to ``Pendiente de
        Entrada`` without an exception.
        """
        ficha_sql, ficha_params = q.build_select_ficha(animal_id)
        ficha_rows = self._executor.execute_sql(ficha_sql, ficha_params)
        ficha = ficha_rows[0] if ficha_rows else None

        intakes_sql, intakes_params = q.build_select_active_intakes(animal_id)
        active_intakes = self._executor.execute_sql(intakes_sql, intakes_params)

        fosters_sql, fosters_params = q.build_select_active_fosters(animal_id)
        active_fosters = self._executor.execute_sql(fosters_sql, fosters_params)

        adoptions_sql, adoptions_params = q.build_select_active_adoptions(animal_id)
        active_adoptions = self._executor.execute_sql(
            adoptions_sql, adoptions_params
        )

        return calculate_state(
            ficha=ficha,
            entradas=active_intakes,
            acogidas=active_fosters,
            adopciones=active_adoptions,
        )

    def persist_animal_state(
        self, animal_id: str, result: DerivationResult
    ) -> None:
        """Upsert the ``animal_current_state`` cache row.

        Writes the derived ``state`` (one of the 12 CHECK-allowed
        strings) and ``state_changed_at = now()``; the
        ``reconciliation_status`` is set to ``matched`` so the
        reconciliation engine stops flagging the row as
        divergent. The categorical ``kind`` is passed through for
        future routing (PR-C may dispatch on it for
        ``pre_death_state`` / ``active_*_id`` writes).
        """
        sql, params = q.build_upsert_current_state(
            animal_id, result.state, _kind_value(result.kind)
        )
        self._executor.execute_sql(sql, params)


def _kind_value(kind: object) -> str:
    """Return the snake_case value of a ``DerivationKind``.

    ``DerivationKind`` is a ``StrEnum`` so ``kind.value`` is the
    snake_case label (e.g. ``"albergue"``). The annotation on
    ``DerivationResult.kind`` is ``object`` to avoid a cycle
    between ``animal_state.py`` and ``result.py``, so this
    helper bridges the runtime shape.
    """
    value = getattr(kind, "value", kind)
    return str(value)


__all__ = ["InsForgeLifecycleAdapter"]
