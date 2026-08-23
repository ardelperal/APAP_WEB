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

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime

from app.core.data_access import SqlExecutor
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
    get_animal_photo_meta_sql,
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
from app.modules.animals.domain.photo import PhotoOutcome
from app.modules.animals.ports.animals_port import AnimalsPort

# Sentinel key the legacy ``photo_service`` recognises: a row with
# ``NombreFoto`` equal to this literal is treated as "the animal has
# no photo on file" and the adapter returns the placeholder PNG so
# the route can render a 200 with a default image instead of 404.
PHOTO_SENTINEL_KEY = "__missing__"

# Tiny 1x1 PNG (67 bytes) the legacy returns when the animal has no
# photo on file. Inline so the placeholder works without touching the
# storage backend at all.
PLACEHOLDER_PHOTO_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03)\x00"
    b"\x05\xfe\x02\xfe\xa3\x35\x81\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


class _PhotoStorageClient:
    """Shape the adapter uses to read a private-bucket object.

    Matches the legacy ``photo_service._PhotoClient`` Protocol
    minimally; the adapter takes it as a constructor arg so tests
    can inject a fake without monkey-patching the storage module.
    """

    def stream_object(self, bucket: str, key: str) -> Iterator[bytes]:  # pragma: no cover
        ...

    @property
    def content_type(self, bucket: str, key: str) -> str:  # pragma: no cover
        ...

    @property
    def content_length(self, bucket: str, key: str) -> int | None:  # pragma: no cover
        ...


class AnimalsInsforgeAdapter(AnimalsPort):
    """InsForge-backed implementation of the animals port."""

    def __init__(
        self,
        client: SqlExecutor,
        storage: _PhotoStorageClient | None = None,
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


def _row_to_animal(row: dict[str, object]) -> Animal:
    """Translate a PostgREST row dict to the hexagonal ``Animal`` entity.

    ``Especie`` and ``Sexo`` come back as strings from the wire; the
    ``StrEnum`` constructor rejects unknown values, matching the
    legacy ``service._row_to_animal`` (the column set is constrained
    to the two enums at the DB level so unknown values would be a
    data-integrity bug, not a runtime event).
    """
    return Animal(
        id=str(row["id"]),
        NCHIP=str(row["NCHIP"]),
        NombreAnimal=str(row["NombreAnimal"]),
        Especie=Especie(str(row["Especie"])),
        Sexo=Sexo(str(row["Sexo"])),
        FNacimiento=str(row["FNacimiento"]),
        activo=bool(row["activo"]),
    )


def _row_to_lifecycle_event(row: dict[str, object]) -> AnimalLifecycleEvent:
    """Translate a PostgREST row dict to the hexagonal ``AnimalLifecycleEvent``.

    ``event_type`` comes back as a string from the wire and goes through
    the ``LifecycleEventType`` StrEnum constructor (same pattern as
    ``_row_to_animal``). The optional lineage fields (``caused_by_event_id``,
    ``source_entity_type``, ``source_entity_id``, ``legacy_source_table``,
    ``legacy_source_id``, ``metadata``) come back as ``None`` when the
    column was NULL on insert; the row dict preserves them as
    SQL NULL → Python ``None`` so the dataclass accepts them.
    """
    return AnimalLifecycleEvent(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        event_type=LifecycleEventType(str(row["event_type"])),
        event_timestamp=str(row["event_timestamp"]),
        created_by=str(row["created_by"]),
        caused_by_event_id=(
            str(row["caused_by_event_id"])
            if row["caused_by_event_id"] is not None
            else None
        ),
        source_entity_type=(
            str(row["source_entity_type"])
            if row["source_entity_type"] is not None
            else None
        ),
        source_entity_id=(
            str(row["source_entity_id"])
            if row["source_entity_id"] is not None
            else None
        ),
        legacy_source_table=(
            str(row["legacy_source_table"])
            if row["legacy_source_table"] is not None
            else None
        ),
        legacy_source_id=(
            int(row["legacy_source_id"])  # type: ignore[call-overload]
            if row["legacy_source_id"] is not None
            else None
        ),
        metadata=(
            row["metadata"]  # type: ignore[arg-type]
            if row["metadata"] is not None
            else None
        ),
    )

    def resolve_animal_photo(
        self, animal_id: str
    ) -> PhotoOutcome | None:
        # Three pre-flight branches, mirroring the legacy
        # ``photo_service.resolve_animal_photo`` exactly:
        # 1. animal does not exist → ``None`` (route renders 404)
        # 2. SQL error on the lookup → ``PhotoOutcome(status="not_found")``
        #    with the placeholder PNG so the client sees a photo
        #    rather than a 404 (legacy fail-closed contract).
        # 3. sentinel key (``NombreFoto == PHOTO_SENTINEL_KEY``) →
        #    ``PhotoOutcome(status="not_found")`` with the placeholder
        #    PNG; the storage backend is never queried.
        try:
            rows = self._client.execute_sql(
                *get_animal_photo_meta_sql(animal_id)
            )
        except Exception:  # noqa: BLE001
            return PhotoOutcome(
                stream=iter([PLACEHOLDER_PHOTO_PNG]),
                content_type="image/png",
                etag="",
                cache_control="private, max-age=3600, must-revalidate",
                content_length=len(PLACEHOLDER_PHOTO_PNG),
                status="not_found",
            )
        if not rows:
            return None

        nombrefoto = rows[0].get("NombreFoto")
        updated_at = rows[0].get("updated_at")
        if nombrefoto == PHOTO_SENTINEL_KEY or self._storage is None:
            return PhotoOutcome(
                stream=iter([PLACEHOLDER_PHOTO_PNG]),
                content_type="image/png",
                etag="",
                cache_control="private, max-age=3600, must-revalidate",
                content_length=len(PLACEHOLDER_PHOTO_PNG),
                status="not_found",
            )

        # Compute the ETag from the (animal_id, updated_at,
        # nombrefoto) tuple. Legacy uses ``hash(...)``; we use sha256
        # here so the ETag is stable across Python runs (hash()
        # is randomised per process via PYTHONHASHSEED).
        etag_payload = f"{animal_id}|{updated_at}|{nombrefoto}".encode()
        etag = f'"{hashlib.sha256(etag_payload).hexdigest()}"'

        try:
            stream = self._storage.stream_object(
                "apap-photos", nombrefoto
            )
            content_type = self._storage.content_type(
                "apap-photos", nombrefoto
            )
            content_length = self._storage.content_length(
                "apap-photos", nombrefoto
            )
        except Exception:  # noqa: BLE001
            # Storage failure → placeholder PNG (legacy fail-closed
            # contract). The route renders 200 with the embedded
            # PNG so the client sees a photo rather than a 5xx.
            return PhotoOutcome(
                stream=iter([PLACEHOLDER_PHOTO_PNG]),
                content_type="image/png",
                etag="",
                cache_control="private, max-age=3600, must-revalidate",
                content_length=len(PLACEHOLDER_PHOTO_PNG),
                status="not_found",
            )

        return PhotoOutcome(
            stream=stream,
            content_type=content_type,
            etag=etag,
            cache_control="private, max-age=3600, must-revalidate",
            content_length=content_length,
            status="ok",
        )


__all__ = ["AnimalsInsforgeAdapter"]
