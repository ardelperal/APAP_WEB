"""InsForge adapter implementing :class:`AnimalsPort` for ``animales``.

The only place in the slice that talks to the InsForge transport
(via :class:`~app.core.data_access.SqlExecutor`). SQL lives in
:mod:`app.modules.animals.adapters.insforge.animals_insforge_queries`
(AGENTS.md §22); this module is pure orchestration. Thin and
stateless; the DI provider in :mod:`app.modules.animals.di.animals_di`
constructs one per request from the already-pooled
:class:`~app.core.insforge.InsForgeClient`.
"""
from __future__ import annotations

import json
from datetime import datetime

from app.core.data_access import SqlExecutor
from app.modules.animals.adapters.insforge.animals_insforge_mappers import (
    _row_to_animal,
    _row_to_lifecycle_event,
)
from app.modules.animals.adapters.insforge.animals_insforge_photo import (
    PhotoStorageClient,
)
from app.modules.animals.adapters.insforge.animals_insforge_photo import (
    resolve_animal_photo as resolve_insforge_animal_photo,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    BEGIN_TX_SQL,
    CHECK_CHIP_UNIQUENESS_SQL,
    COMMIT_TX_SQL,
    GET_CURRENT_CHIP_SQL,
    INSERT_CHIP_CHANGED_EVENT_SQL,
    ROLLBACK_TX_SQL,
    UPDATE_ACOGIDAS_CHIP_SQL,
    UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL,
    UPDATE_ADOPCIONES_CHIP_SQL,
    UPDATE_ANIMALS_CHIP_SQL,
    UPDATE_ENTRADAS_CHIP_SQL,
    UPDATE_TERAPIAS_CHIP_SQL,
    create_animal_sql,
    delete_animal_sql,
    get_animal_by_nchip_sql,
    list_animals_sql,
    list_lifecycle_events_sql,
    record_lifecycle_event_sql,
    update_animal_sql,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)
from app.modules.animals.ports.animals_port import AnimalsPort
from app.modules.animals.ports.photo_asset import PhotoAsset


class AnimalsInsforgeAdapter(AnimalsPort):
    """InsForge-backed implementation of the animals port."""

    def __init__(
        self,
        client: SqlExecutor,
        storage: PhotoStorageClient,
    ) -> None:
        self._client = client
        self._storage = storage

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        sql, params = get_animal_by_nchip_sql(nchip)
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def list_animals(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[Animal]:
        sql, params = list_animals_sql(
            limit=limit,
            offset=offset,
            activo_only=activo_only,
        )
        rows = self._client.execute_sql(sql, params)
        return [_row_to_animal(row) for row in rows]

    def create_animal(
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
    ) -> Animal:
        sql, params = create_animal_sql(
            nchip=nchip,
            nombre=nombre,
            especie=especie.value,
            sexo=sexo.value,
            fnacimiento=fnacimiento,
        )
        rows = self._client.execute_sql(sql, params)
        # ``INSERT ... RETURNING`` always yields one row on success;
        # the empty-list branch is a defensive guard for an
        # unexpected transport shape (would surface as an opaque
        # ``IndexError`` otherwise, which is harder to diagnose).
        if not rows:
            raise RuntimeError(  # noqa: TRY003 — operator-facing diagnostic
                "INSERT INTO animales RETURNING produced no rows — "
                "the transport shape has drifted, expected exactly "
                "one row"
            )
        return _row_to_animal(rows[0])

    def update_animal(
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
    ) -> Animal | None:
        # ``None``-skip on the SQL side is delegated to the helper;
        # if every field is ``None`` the helper returns ``None`` and
        # we short-circuit before touching the transport (the
        # partial UPDATE would be a no-op anyway, and the route
        # handler should not pay for a round-trip).
        sql_params = update_animal_sql(
            animal_id=animal_id,
            nombre=nombre,
            especie=None if especie is None else especie.value,
            sexo=None if sexo is None else sexo.value,
            fnacimiento=fnacimiento,
        )
        if sql_params is None:
            # All kwargs were ``None``: surface the no-op by reading
            # the row back via the same primary-key lookup the legacy
            # code uses (would happen via get_animal, but importing
            # the helper into itself is awkward — re-query is cheap).
            return self.get_animal_by_id(animal_id)
        sql, params = sql_params
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def get_animal_by_id(self, animal_id: str) -> Animal | None:
        """Read-only helper used by ``update_animal``'s no-op branch.

        Not part of the public ``AnimalsPort`` surface — it's a
        private adapter implementation detail (the no-op branch
        could equivalently return a sentinel, but reading the row
        back keeps the contract symmetric with the legacy
        ``update_animal`` which also returns the row unchanged).
        """
        rows = self._client.execute_sql(
            "SELECT id, \"NCHIP\", \"NombreAnimal\", \"Especie\", \"Sexo\", "
            "\"FNacimiento\", activo FROM animales WHERE id = $1",
            [animal_id],
        )
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def delete_animal(self, animal_id: str) -> Animal | None:
        sql, params = delete_animal_sql(animal_id)
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def record_lifecycle_event(
        self,
        *,
        animal_id: str,
        event_type: LifecycleEventType,
        event_timestamp: str | datetime,
        created_by: str,
        caused_by_event_id: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        legacy_source_table: str | None = None,
        legacy_source_id: int | None = None,
        metadata: dict | None = None,
    ) -> AnimalLifecycleEvent:
        # ``event_timestamp`` may come in as a ``datetime`` (route layer
        # parses from a form). The legacy SQL expects ISO 8601 text so
        # we normalise here; ``isoformat()`` is a no-op on an already-
        # formatted string for the postgres driver we use.
        timestamp_str = (
            event_timestamp.isoformat()
            if isinstance(event_timestamp, datetime)
            else event_timestamp
        )
        sql, params = record_lifecycle_event_sql(
            animal_id=animal_id,
            event_type=event_type.value,
            event_timestamp=timestamp_str,
            created_by=created_by,
            caused_by_event_id=caused_by_event_id,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            legacy_source_table=legacy_source_table,
            legacy_source_id=legacy_source_id,
            metadata=metadata,
        )
        rows = self._client.execute_sql(sql, params)
        # ``ON CONFLICT DO NOTHING`` returns the EXISTING row (the
        # conflict target) so the caller sees the persisted shape
        # regardless of whether the insert raced. ``RETURNING`` is
        # empty only when the row is genuinely absent — that should
        # not happen given the table's NOT NULL constraints on every
        # required column, so an empty result here is a transport-
        # shape drift.
        if not rows:
            raise RuntimeError(  # noqa: TRY003 — operator-facing diagnostic
                "INSERT INTO animal_lifecycle_events ON CONFLICT DO "
                "NOTHING RETURNING produced no rows; the transport "
                "shape has drifted, expected exactly one row."
            )
        return _row_to_lifecycle_event(rows[0])

    def list_lifecycle_events(
        self,
        animal_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_types: list[LifecycleEventType] | None = None,
    ) -> list[AnimalLifecycleEvent]:
        # Empty ``event_types`` would short-circuit to ``WHERE animal_id
        # = $1 AND event_type = ANY($2::text[])`` which on postgres is
        # ``FALSE`` for all rows — call the no-filter path instead so
        # the caller sees the full timeline.
        event_type_strings = (
            [et.value for et in event_types] if event_types else None
        )
        sql, params = list_lifecycle_events_sql(
            animal_id=animal_id,
            limit=limit,
            offset=offset,
            event_types=event_type_strings,
        )
        rows = self._client.execute_sql(sql, params)
        return [_row_to_lifecycle_event(row) for row in rows]

    def change_animal_chip(
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
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

    def resolve_animal_photo(
        self, animal_id: str
    ) -> PhotoAsset | None:
        return resolve_insforge_animal_photo(
            self._client,
            self._storage,
            animal_id,
        )
__all__ = ["AnimalsInsforgeAdapter"]
