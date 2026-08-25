"""Transactional InsForge cascade for changing an animal chip.

The saga lives apart from the main CRUD adapter because its atomic multi-table
updates and rollback handling carry substantially more transactional complexity.
Keeping that workflow isolated preserves saga atomicity while leaving the main
adapter focused on the ordinary animals CRUD surface.
"""

from __future__ import annotations

import json

from app.core.data_access import SqlExecutor
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import LifecycleEventType

# ``chip_cascade`` — saga SQL constants (issue #29, LIFECYCLE-04).
# All UPDATEs carry ``RETURNING id`` so the adapter can count the
# affected rows per table without an extra round-trip. The legacy
# pre-flight checks (uniqueness of ``new_chip``; current chip
# matches ``old_chip``) live in separate SELECTs because they read
# before the transaction opens.
CHECK_CHIP_UNIQUENESS_SQL: str = (
    'SELECT id FROM animales WHERE "NCHIP" = $1 AND id != $2 LIMIT 1'
)

GET_CURRENT_CHIP_SQL: str = (
    'SELECT "NCHIP" FROM animales WHERE id = $1'
)

UPDATE_ANIMALS_CHIP_SQL: str = (
    'UPDATE animales SET "NCHIP" = $1, updated_at = now() '
    'WHERE id = $2 AND "NCHIP" = $3 '
    "RETURNING id"
)

UPDATE_ENTRADAS_CHIP_SQL: str = (
    "UPDATE entradas SET chip = $1, updated_at = now() "
    "WHERE chip = $2 AND activo = true "
    "RETURNING id"
)

UPDATE_ACOGIDAS_CHIP_SQL: str = (
    "UPDATE acogidas SET chip = $1, updated_at = now() "
    "WHERE chip = $2 AND activo = true "
    "RETURNING id"
)

UPDATE_ADOPCIONES_CHIP_SQL: str = (
    "UPDATE adopciones SET chip = $1, updated_at = now() "
    "WHERE chip = $2 AND activo = true "
    "RETURNING id"
)

UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL: str = (
    "UPDATE actuaciones_sanitarias SET chip = $1, updated_at = now() "
    "WHERE chip = $2 "
    "RETURNING id"
)

UPDATE_TERAPIAS_CHIP_SQL: str = (
    "UPDATE terapias SET chip = $1, updated_at = now() "
    "WHERE chip = $2 "
    "RETURNING id"
)

INSERT_CHIP_CHANGED_EVENT_SQL: str = (
    "INSERT INTO animal_lifecycle_events ("
    "animal_id, event_type, event_timestamp, metadata, created_by"
    ") VALUES ($1, $2, now(), $3, $4) "
    "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING"
)

BEGIN_TX_SQL: str = "BEGIN"
COMMIT_TX_SQL: str = "COMMIT"
ROLLBACK_TX_SQL: str = "ROLLBACK"


class AnimalsInsforgeChipCascade:
    """Run the atomic multi-table chip-change saga through one SQL executor."""

    def __init__(self, client: SqlExecutor) -> None:
        self._client = client

    def change_animal_chip(
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
        new_chip = new_chip.strip()
        if not new_chip:
            raise ValueError("new_chip es obligatorio y no puede estar vacio")
        if new_chip == old_chip:
            raise ValueError("new_chip no puede ser igual a old_chip")
        reason = reason.strip()
        if not reason:
            raise ValueError("reason es obligatorio y no puede estar vacio")

        # Two pre-flight SELECTs run BEFORE the transaction opens:
        # uniqueness of the new chip (no other animal carries it) and
        # the current chip on this animal (must match ``old_chip`` so
        # the UPDATEs don't no-op every row). Both are SELECTs — they
        # don't take a write lock until the subsequent UPDATE.
        uniqueness_rows = self._client.execute_sql(
            CHECK_CHIP_UNIQUENESS_SQL,
            [new_chip, animal_id],
        )
        if uniqueness_rows:
            return ChangeChipResult(
                success=False,
                old_chip=old_chip,
                new_chip=new_chip,
                updated_tables={},
                error=(
                    f"new_chip {new_chip!r} ya está asignado a otro animal"
                ),
            )
        current_rows = self._client.execute_sql(
            GET_CURRENT_CHIP_SQL, [animal_id]
        )
        if not current_rows:
            return ChangeChipResult(
                success=False,
                old_chip=old_chip,
                new_chip=new_chip,
                updated_tables={},
                error=f"animal_id {animal_id!r} no existe",
            )
        current_chip = str(current_rows[0]["NCHIP"])
        if current_chip != old_chip:
            return ChangeChipResult(
                success=False,
                old_chip=old_chip,
                new_chip=new_chip,
                updated_tables={},
                error=(
                    f"old_chip {old_chip!r} no coincide con el chip "
                    f"actual {current_chip!r}; recargue la ficha"
                ),
            )

        # Transaction body. We accumulate the per-table row counts
        # even on failure so the operator can audit the partial
        # damage (everything rolls back together, so the count is
        # informational only).
        updated: dict[str, int] = {}
        try:
            self._client.execute_sql(BEGIN_TX_SQL)

            rows = self._client.execute_sql(
                UPDATE_ANIMALS_CHIP_SQL,
                [new_chip, animal_id, old_chip],
            )
            updated["animals"] = len(rows)

            updated["entradas"] = len(
                self._client.execute_sql(
                    UPDATE_ENTRADAS_CHIP_SQL, [new_chip, old_chip]
                )
            )
            updated["acogidas"] = len(
                self._client.execute_sql(
                    UPDATE_ACOGIDAS_CHIP_SQL, [new_chip, old_chip]
                )
            )
            updated["adopciones"] = len(
                self._client.execute_sql(
                    UPDATE_ADOPCIONES_CHIP_SQL, [new_chip, old_chip]
                )
            )
            updated["actuaciones_sanitarias"] = len(
                self._client.execute_sql(
                    UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL,
                    [new_chip, old_chip],
                )
            )
            updated["terapias"] = len(
                self._client.execute_sql(
                    UPDATE_TERAPIAS_CHIP_SQL, [new_chip, old_chip]
                )
            )

            metadata_json = json.dumps(
                {
                    "old_chip": old_chip,
                    "new_chip": new_chip,
                    "reason": reason,
                }
            )
            self._client.execute_sql(
                INSERT_CHIP_CHANGED_EVENT_SQL,
                [
                    animal_id,
                    LifecycleEventType.CHIP_CHANGED.value,
                    metadata_json,
                    operador_user_id,
                ],
            )

            self._client.execute_sql(COMMIT_TX_SQL)

            return ChangeChipResult(
                success=True,
                old_chip=old_chip,
                new_chip=new_chip,
                updated_tables=updated,
            )

        except Exception as exc:  # noqa: BLE001
            # Any failure inside the transaction body: roll back and
            # surface the error. ``updated`` already carries whatever
            # the saga managed to do before failing — informative for
            # the operator even though everything was rolled back.
            # If the ROLLBACK itself fails (network drop, server gone),
            # the connection state is unrecoverable anyway; we keep the
            # original error as the primary cause and append the rollback
            # failure for the operator's audit trail.
            rollback_error: str | None = None
            try:
                self._client.execute_sql(ROLLBACK_TX_SQL)
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_error = repr(rollback_exc)
            base_error = f"Error en la transaccion: {exc}"
            error = (
                f"{base_error}; rollback fallo: {rollback_error}"
                if rollback_error
                else base_error
            )
            return ChangeChipResult(
                success=False,
                old_chip=old_chip,
                new_chip=new_chip,
                updated_tables=updated,
                error=error,
            )


__all__ = ["AnimalsInsforgeChipCascade"]
