"""Direct coverage for the CRITICAL_HELPERS row mappers in
``animals_local_backend_mappers.py`` (pyproject.toml [tool.apap.coverage_gate]).

``_row_to_lifecycle_event`` is exercised indirectly by
``animals_local_backend_lifecycle.py``'s own tests, but those mock at the
executor level and never actually decode a row through this function.
These atoms pin its field mapping directly.
"""

from __future__ import annotations

from app.modules.animals.adapters.local_backend.animals_local_backend_mappers import (
    _row_to_lifecycle_event,
)
from app.modules.animals.domain.lifecycle_event import LifecycleEventType


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "evt-1",
        "animal_id": "animal-1",
        "event_type": "INTAKE_STARTED",
        "event_timestamp": "2026-01-01T00:00:00Z",
        "created_by": "u-1",
        "caused_by_event_id": None,
        "source_entity_type": None,
        "source_entity_id": None,
        "legacy_source_table": None,
        "legacy_source_id": None,
        "metadata": None,
    }
    base.update(overrides)
    return base


def test_maps_required_fields() -> None:
    event = _row_to_lifecycle_event(_row())

    assert event.id == "evt-1"
    assert event.animal_id == "animal-1"
    assert event.event_type == LifecycleEventType.INTAKE_STARTED
    assert event.event_timestamp == "2026-01-01T00:00:00Z"
    assert event.created_by == "u-1"
    assert event.caused_by_event_id is None
    assert event.source_entity_type is None
    assert event.source_entity_id is None
    assert event.legacy_source_table is None
    assert event.legacy_source_id is None
    assert event.metadata is None


def test_maps_optional_fields_when_present() -> None:
    event = _row_to_lifecycle_event(
        _row(
            caused_by_event_id="evt-0",
            source_entity_type="foster_assignment",
            source_entity_id="fa-1",
            legacy_source_table="TbHistorial",
            legacy_source_id=42,
            metadata={"note": "seeded"},
        )
    )

    assert event.caused_by_event_id == "evt-0"
    assert event.source_entity_type == "foster_assignment"
    assert event.source_entity_id == "fa-1"
    assert event.legacy_source_table == "TbHistorial"
    assert event.legacy_source_id == 42
    assert event.metadata == {"note": "seeded"}
