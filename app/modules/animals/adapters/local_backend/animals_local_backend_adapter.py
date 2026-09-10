"""LocalBackend adapter implementing :class:`AnimalsPort` for ``animales``.

The only place in the slice that talks to the LocalBackend transport
(via :class:`~app.core.data_access.SqlExecutor`). SQL lives in
:mod:`app.modules.animals.adapters.local_backend.animals_local_backend_queries`
(AGENTS.md §22); this module is pure orchestration. Thin and
stateless; the DI provider in :mod:`app.modules.animals.di.animals_di`
constructs one per request from the already-pooled
:class:`~app.core.local_backend.LocalPostgresExecutor`.
"""

# ruff: noqa: N803 — kwargs intentionally preserve legacy schema column names
from __future__ import annotations

from datetime import datetime

from app.core.data_access import SqlExecutor
from app.modules.animals.adapters.local_backend.animals_local_backend_chip_cascade import (
    AnimalsLocalBackendChipCascade,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_lifecycle import (
    list_lifecycle_events as list_local_backend_lifecycle_events,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_lifecycle import (
    record_lifecycle_event as record_local_backend_lifecycle_event,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_mappers import (
    _row_to_animal,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_photo import (
    PhotoStorageClient,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_photo import (
    resolve_animal_photo as resolve_local_backend_animal_photo,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_queries import (
    GET_ANIMAL_BY_ID_SQL,
    count_animals_sql,
    get_animal_by_nchip_sql,
    list_animals_sql,
    search_animals_sql,
)
from app.modules.animals.adapters.local_backend.animals_local_backend_write_queries import (
    create_animal_sql,
    delete_animal_sql,
    update_animal_sql,
)
from app.modules.animals.domain.animal import (
    Animal,
    AnimalSearchResult,
    Especie,
    Sexo,
)
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)
from app.modules.animals.ports.animals_port import AnimalsPort
from app.modules.animals.ports.photo_asset import PhotoAsset


def _search_total(rows: list[dict[str, object]]) -> int:
    """Return the count-query total, defaulting an empty result to zero."""
    return int(str(rows[0]["total"])) if rows else 0


class AnimalsLocalBackendAdapter(AnimalsPort):
    """LocalBackend-backed implementation of the animals port."""

    def __init__(
        self,
        client: SqlExecutor,
        storage: PhotoStorageClient | None,
    ) -> None:
        self._client = client
        self._storage = storage
        self._chip_cascade = AnimalsLocalBackendChipCascade(client)

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        sql, params = get_animal_by_nchip_sql(nchip)
        rows = self._client.execute_sql(sql, params)
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def get_animal_by_id(self, animal_id: str) -> Animal | None:
        """Return the animal with this database primary key, if present."""
        rows = self._client.execute_sql(GET_ANIMAL_BY_ID_SQL, [animal_id])
        if not rows:
            return None
        return _row_to_animal(rows[0])

    def search_animals(  # noqa: PLR0913  # 9 filter args are minimal for the search route surface; extract a dataclass if a 10th filter is added
        self,
        *,
        q: str | None = None,
        chip: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        estado: str | None = None,
        fecha_alta_since: str | None = None,
        fecha_alta_until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnimalSearchResult:
        """Return one filtered page and a separate unpaginated total."""
        filters = {
            "q": q,
            "chip": chip,
            "especie": getattr(especie, "value", None),
            "sexo": getattr(sexo, "value", None),
            "estado": estado,
            "fecha_alta_since": fecha_alta_since,
            "fecha_alta_until": fecha_alta_until,
        }
        count_sql, count_params = count_animals_sql(**filters)
        if limit == 0:
            count_rows = self._client.execute_sql(count_sql, count_params)
            total = _search_total(count_rows)
            return AnimalSearchResult(data=(), total=total, limit=0, offset=offset)

        data_sql, data_params = search_animals_sql(
            **filters,
            limit=limit,
            offset=offset,
        )
        rows = self._client.execute_sql(data_sql, data_params)
        count_rows = self._client.execute_sql(count_sql, count_params)
        total = _search_total(count_rows)
        return AnimalSearchResult(
            data=tuple(_row_to_animal(row) for row in rows),
            total=total,
            limit=limit,
            offset=offset,
        )

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
        **optional_fields: str | None,
    ) -> Animal:
        sql, params = create_animal_sql(
            nchip=nchip,
            nombre=nombre,
            especie=especie.value,
            sexo=sexo.value,
            fnacimiento=fnacimiento,
            **optional_fields,
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
        **optional_fields: str | None,
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
            **optional_fields,
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
        return record_local_backend_lifecycle_event(
            self._client,
            animal_id=animal_id,
            event_type=event_type,
            event_timestamp=event_timestamp,
            created_by=created_by,
            caused_by_event_id=caused_by_event_id,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            legacy_source_table=legacy_source_table,
            legacy_source_id=legacy_source_id,
            metadata=metadata,
        )

    def list_lifecycle_events(
        self,
        animal_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_types: list[LifecycleEventType] | None = None,
    ) -> list[AnimalLifecycleEvent]:
        return list_local_backend_lifecycle_events(
            self._client,
            animal_id,
            limit=limit,
            offset=offset,
            event_types=event_types,
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
        return self._chip_cascade.change_animal_chip(
            animal_id=animal_id,
            old_chip=old_chip,
            new_chip=new_chip,
            reason=reason,
            operador_user_id=operador_user_id,
        )

    def resolve_animal_photo(
        self, animal_id: str
    ) -> PhotoAsset | None:
        return resolve_local_backend_animal_photo(
            self._client,
            self._storage,
            animal_id,
        )
__all__ = ["AnimalsLocalBackendAdapter"]
