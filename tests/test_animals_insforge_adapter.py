"""InsForge-adapter tests for the animals slice."""
from __future__ import annotations

from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    get_animal_by_nchip_sql,
)


class _FakeClient:
    """In-memory :class:`~app.core.data_access.SqlExecutor` for unit tests."""

    def __init__(self, rows: list[dict[str, object]] | Exception) -> None:
        self._rows = rows
        self.last_query: str | None = None
        self.last_params: list[object] | None = None

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.last_query = query
        self.last_params = params
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


def test_returns_none_when_no_match() -> None:
    """An empty result set yields ``None`` (not an exception)."""
    client = _FakeClient(rows=[])
    adapter = AnimalsInsforgeAdapter(client=client)  # type: ignore[arg-type]
    assert adapter.get_animal_by_nchip("941000000012345") is None
    sql, params = get_animal_by_nchip_sql("941000000012345")
    assert client.last_query == sql
    assert client.last_params == params


def test_maps_row_to_domain() -> None:
    """A result row is mapped to the hexagonal :class:`Animal` dataclass."""
    client = _FakeClient(
        rows=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "NCHIP": "941000000012345",
                "NombreAnimal": "Luna",
                "Especie": "CANINA",
                "Sexo": "H",
                "FNacimiento": "2024-03-01",
                "activo": True,
            }
        ]
    )
    adapter = AnimalsInsforgeAdapter(client=client)  # type: ignore[arg-type]
    animal = adapter.get_animal_by_nchip("941000000012345")
    assert animal is not None
    assert animal.NCHIP == "941000000012345"
    assert animal.NombreAnimal == "Luna"
    assert animal.activo is True


def test_maps_lifecycle_event_row_to_domain() -> None:
    """A lifecycle-event row is mapped to the hexagonal ``AnimalLifecycleEvent``.

    Pins the ``_row_to_lifecycle_event`` helper's coverage at 100%
    (the coverage-gate auto-discovers every ``_row_to_*`` function and
    rejects any that drops below full line coverage). Tests every
    column translation including the optional lineage fields (None
    when the row has them NULL) and the JSONB metadata round-trip.
    """
    from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
        _row_to_lifecycle_event,
    )
    from app.modules.animals.domain.lifecycle_event import LifecycleEventType

    row = {
        "id": "00000000-0000-0000-0000-000000000077",
        "animal_id": "00000000-0000-0000-0000-000000000042",
        "event_type": "INTAKE_STARTED",
        "event_timestamp": "2024-03-01T10:00:00+00:00",
        "created_by": "operator@apap.local",
        "caused_by_event_id": "00000000-0000-0000-0000-000000000050",
        "source_entity_type": "adopcion",
        "source_entity_id": "42",
        "legacy_source_table": "adopciones",
        "legacy_source_id": 123,
        "metadata": {"destino": "adoptante1"},
    }
    event = _row_to_lifecycle_event(row)
    assert event.id == row["id"]
    assert event.animal_id == row["animal_id"]
    assert event.event_type is LifecycleEventType.INTAKE_STARTED
    assert event.event_timestamp == row["event_timestamp"]
    assert event.created_by == row["created_by"]
    assert event.caused_by_event_id == row["caused_by_event_id"]
    assert event.source_entity_type == row["source_entity_type"]
    assert event.source_entity_id == row["source_entity_id"]
    assert event.legacy_source_table == row["legacy_source_table"]
    assert event.legacy_source_id == 123
    assert event.metadata == {"destino": "adoptante1"}


def test_maps_lifecycle_event_row_with_null_lineage() -> None:
    """A row with NULL lineage fields round-trips with None values."""
    from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
        _row_to_lifecycle_event,
    )
    from app.modules.animals.domain.lifecycle_event import LifecycleEventType

    row = {
        "id": "00000000-0000-0000-0000-000000000077",
        "animal_id": "00000000-0000-0000-0000-000000000042",
        "event_type": "STATE_CORRECTION",
        "event_timestamp": "2024-03-01T10:00:00+00:00",
        "created_by": "operator@apap.local",
        "caused_by_event_id": None,
        "source_entity_type": None,
        "source_entity_id": None,
        "legacy_source_table": None,
        "legacy_source_id": None,
        "metadata": None,
    }
    event = _row_to_lifecycle_event(row)
    assert event.event_type is LifecycleEventType.STATE_CORRECTION
    assert event.caused_by_event_id is None
    assert event.source_entity_type is None
    assert event.source_entity_id is None
    assert event.legacy_source_table is None
    assert event.legacy_source_id is None
    assert event.metadata is None
