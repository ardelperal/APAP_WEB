"""Transactional LocalBackend saga for changing an animal chip (issue #916, A-04).

The saga lives apart from the main CRUD adapter because its atomic
multi-statement unit of work carries substantially more transactional
complexity. Keeping that workflow isolated preserves saga atomicity while
leaving the main adapter focused on the ordinary animals CRUD surface.

The unit of work is deliberately small: dependent tables (``entradas``,
``acogidas``, ``adopciones``, ``actuacion_sanitaria``, ``terapias``) do NOT
carry a ``chip`` copy — they reference the animal through the surrogate FK
``animal_id UUID REFERENCES animales(id)``. Legacy Access propagated NCHIP
because NCHIP was the legacy join key; the web schema replaced that join
key with the FK, so a dependent-table UPDATE cascade is unnecessary (see
``docs/architecture/decisiones-proyecto.md`` and
``docs/discovery/feature-01-animal-lifecycle.md``). Pre-#916 the saga sent
``BEGIN``/``COMMIT``/``ROLLBACK`` through ``execute_sql``, which opens a
NEW connection per call and protected nothing, and its dependent UPDATEs
failed with ``UndefinedColumn`` in production.

Atomicity comes from :meth:`LocalPostgresExecutor.transaction` (pattern of
``app/modules/adopciones/service.py::create_adoption`` after issue #914):
the guarded ``UPDATE animales`` and the ``CHIP_CHANGED`` event commit
together or not at all, and any failure rolls the unit back before the
exception surfaces here as a failure result.
"""


from __future__ import annotations

import json

from app.core.data_access import SqlExecutor, TransactionalSqlExecutor
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import LifecycleEventType

# ``chip_cascade`` — saga SQL constants (issue #29, LIFECYCLE-04).
# The pre-flight checks (uniqueness of ``new_chip``; current chip matches
# ``old_chip``) are read-only SELECTs that run before the transaction opens.
CHECK_CHIP_UNIQUENESS_SQL: str = (
    "SELECT id FROM animales WHERE nchip = $1 AND id != $2 LIMIT 1"
)

GET_CURRENT_CHIP_SQL: str = (
    'SELECT nchip AS "NCHIP" FROM animales WHERE id = $1'
)

UPDATE_ANIMALS_CHIP_SQL: str = (
    "UPDATE animales SET nchip = $1, updated_at = now() "
    "WHERE id = $2 AND nchip = $3 "
    "RETURNING id"
)

INSERT_CHIP_CHANGED_EVENT_SQL: str = (
    "INSERT INTO animal_lifecycle_events ("
    "animal_id, event_type, event_timestamp, metadata, created_by"
    ") VALUES ($1, $2, now(), $3, $4) "
    "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING"
)


def _require_nonblank(value: str, name: str) -> str:
    """Return a stripped required value or raise the legacy validation error."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} es obligatorio y no puede estar vacio")
    return stripped


def _require_different(value: str, previous: str, name: str) -> None:
    """Reject a replacement value that is unchanged."""
    if value == previous:
        raise ValueError(f"{name} no puede ser igual a old_chip")


class AnimalsLocalBackendChipCascade:
    """Run the atomic chip-change saga through one SQL executor."""

    def __init__(self, client: TransactionalSqlExecutor) -> None:
        self._client = client

    @staticmethod
    def _preflight_failure(
        old_chip: str,
        new_chip: str,
        error: str,
    ) -> ChangeChipResult:
        """Build the shared fail-closed preflight result."""
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip,
            updated_tables={},
            error=error,
        )

    def _duplicate_chip_failure(
        self,
        animal_id: str,
        old_chip: str,
        new_chip: str,
    ) -> ChangeChipResult | None:
        """Return a conflict result when another animal owns the new chip."""
        rows = self._client.execute_sql(
            CHECK_CHIP_UNIQUENESS_SQL,
            [new_chip, animal_id],
        )
        if rows:
            return self._preflight_failure(
                old_chip,
                new_chip,
                f"new_chip {new_chip!r} ya está asignado a otro animal",
            )
        return None

    def _current_chip_failure(
        self,
        animal_id: str,
        old_chip: str,
        new_chip: str,
    ) -> ChangeChipResult | None:
        """Return the missing or stale-chip preflight result, if any."""
        rows = self._client.execute_sql(GET_CURRENT_CHIP_SQL, [animal_id])
        if not rows:
            return self._preflight_failure(
                old_chip,
                new_chip,
                f"animal_id {animal_id!r} no existe",
            )
        return self._chip_mismatch_failure(
            str(rows[0]["NCHIP"]), old_chip, new_chip
        )

    def _chip_mismatch_failure(
        self,
        current_chip: str,
        old_chip: str,
        new_chip: str,
    ) -> ChangeChipResult | None:
        """Return a stale-form result when the persisted chip changed."""
        if current_chip != old_chip:
            return self._preflight_failure(
                old_chip,
                new_chip,
                (
                    f"old_chip {old_chip!r} no coincide con el chip "
                    f"actual {current_chip!r}; recargue la ficha"
                ),
            )
        return None

    def _preflight(
        self,
        animal_id: str,
        old_chip: str,
        new_chip: str,
    ) -> ChangeChipResult | None:
        """Run both read-only checks before opening the transaction."""
        return self._duplicate_chip_failure(
            animal_id, old_chip, new_chip
        ) or self._current_chip_failure(animal_id, old_chip, new_chip)

    def _update_animal_chip(
        self,
        tx: SqlExecutor,
        animal_id: str,
        old_chip: str,
        new_chip: str,
    ) -> int:
        """Update ``animales.nchip`` guarded by ``old_chip``.

        Raises when the guard matches no row: the preflight SELECT and the
        UPDATE run in separate connections, so a concurrent chip change
        between them must abort the unit of work instead of writing an
        event for a chip that never moved.
        """
        rows = tx.execute_sql(
            UPDATE_ANIMALS_CHIP_SQL,
            [new_chip, animal_id, old_chip],
        )
        if not rows:
            raise ValueError(
                f"old_chip {old_chip!r} no coincide con el chip actual; "
                "recargue la ficha"
            )
        return len(rows)

    def _record_event(  # noqa: PLR0913  # private saga step: bound executor + the 5 event fields (animal, chips, reason, actor)
        self,
        tx: SqlExecutor,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> None:
        """Append the audit event inside the open transaction."""
        metadata_json = json.dumps(
            {
                "old_chip": old_chip,
                "new_chip": new_chip,
                "reason": reason,
            }
        )
        tx.execute_sql(
            INSERT_CHIP_CHANGED_EVENT_SQL,
            [
                animal_id,
                LifecycleEventType.CHIP_CHANGED.value,
                metadata_json,
                operador_user_id,
            ],
        )

    @staticmethod
    def _build_failure(
        old_chip: str,
        new_chip: str,
        exc: Exception,
    ) -> ChangeChipResult:
        """Build the transaction-failure result (already rolled back).

        ``updated_tables`` stays empty: the real rollback means nothing
        persisted, so reporting row counts would mislead the operator.
        """
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip,
            updated_tables={},
            error=f"Error en la transaccion: {exc}",
        )

    def _execute_cascade(
        self,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
        """Run the mutation body inside one real ``transaction()``.

        The transaction commits on clean exit; any exception rolls the
        whole unit back before surfacing here as a failure result, so the
        operator never observes a chip change without its audit event.
        """
        updated: dict[str, int] = {}
        try:
            with self._client.transaction() as tx:
                updated["animals"] = self._update_animal_chip(
                    tx, animal_id, old_chip, new_chip
                )
                self._record_event(
                    tx, animal_id, old_chip, new_chip, reason, operador_user_id
                )
        except Exception as exc:  # noqa: BLE001
            return self._build_failure(old_chip, new_chip, exc)
        return ChangeChipResult(
            success=True,
            old_chip=old_chip,
            new_chip=new_chip,
            updated_tables=updated,
        )

    def change_animal_chip(
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
        new_chip = _require_nonblank(new_chip, "new_chip")
        _require_different(new_chip, old_chip, "new_chip")
        reason = _require_nonblank(reason, "reason")

        # Two pre-flight SELECTs run BEFORE the transaction opens:
        # uniqueness of the new chip (no other animal carries it) and
        # the current chip on this animal (must match ``old_chip`` so
        # the guarded UPDATE cannot no-op). The guarded UPDATE still
        # re-checks ``old_chip`` at write time to close the race window
        # between these SELECTs and the transaction body.
        preflight_failure = self._preflight(animal_id, old_chip, new_chip)
        if preflight_failure is not None:
            return preflight_failure

        return self._execute_cascade(
            animal_id, old_chip, new_chip, reason, operador_user_id
        )


__all__ = ["AnimalsLocalBackendChipCascade"]
