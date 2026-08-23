"""Application-layer tests for ``record_lifecycle_event`` (slice #420-7 sixth surface).

Mirrors the stub-port pattern from the previous application-layer
tests in this slice so the use-case stays transport-free: the
application code never sees ``InsForgeClient`` or ``SqlExecutor``;
it talks to the :class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.animals.application.record_lifecycle_event import (
    LifecycleEventValidationError,
    record_lifecycle_event,
)
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.last_event_type: LifecycleEventType | None = None
        self.last_event_timestamp: str | datetime | None = None
        self.last_created_by: str | None = None
        self.last_caused_by_event_id: str | None = None
        self.last_source_entity_type: str | None = None
        self.last_source_entity_id: str | None = None
        self.last_legacy_source_table: str | None = None
        self.last_legacy_source_id: int | None = None
        self.last_metadata: dict | None = None
        self.next_event: AnimalLifecycleEvent | None = None

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
        self.last_animal_id = animal_id
        self.last_event_type = event_type
        self.last_event_timestamp = event_timestamp
        self.last_created_by = created_by
        self.last_caused_by_event_id = caused_by_event_id
        self.last_source_entity_type = source_entity_type
        self.last_source_entity_id = source_entity_id
        self.last_legacy_source_table = legacy_source_table
        self.last_legacy_source_id = legacy_source_id
        self.last_metadata = metadata
        if self.next_event is None:
            raise AssertionError(
                "stub next_event unset; set it in the test before "
                "calling record_lifecycle_event"
            )
        return self.next_event

    # No-op stubs for the other Protocol methods so the runtime
    # check on ``runtime_checkable`` does not trip if the stub is
    # incidentally validated elsewhere.
    def get_animal_by_nchip(self, nchip: str) -> object:  # pragma: no cover
        return None

    def list_animals(  # pragma: no cover
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[object]:
        return []

    def create_animal(  # pragma: no cover
        self,
        *,
        nchip: str,
        nombre: str,
        especie: object,
        sexo: object,
        fnacimiento: str,
    ) -> object:
        raise NotImplementedError

    def update_animal(  # pragma: no cover
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: object | None = None,
        sexo: object | None = None,
        fnacimiento: str | None = None,
    ) -> object | None:
        raise NotImplementedError

    def delete_animal(self, animal_id: str) -> object | None:  # pragma: no cover
        return None


def _event() -> AnimalLifecycleEvent:
    return AnimalLifecycleEvent(
        id="00000000-0000-0000-0000-000000000077",
        animal_id="00000000-0000-0000-0000-000000000042",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp="2024-03-01T10:00:00+00:00",
        created_by="user@example.com",
    )


def test_happy_path_minimal_kwargs() -> None:
    """The minimum surface (animal_id, event_type, event_timestamp, created_by)
    round-trips to the port and returns the adapter-built event."""
    port = _StubPort()
    port.next_event = _event()

    result = record_lifecycle_event(
        port,
        animal_id=" id-with-spaces ",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp="2024-03-01T10:00:00+00:00",
        created_by=" operator@apap.local ",
    )

    assert result is port.next_event
    assert port.last_animal_id == "id-with-spaces"
    assert port.last_event_type is LifecycleEventType.INTAKE_STARTED
    assert port.last_event_timestamp == "2024-03-01T10:00:00+00:00"
    assert port.last_created_by == "operator@apap.local"
    # Optional lineage fields default to None
    assert port.last_caused_by_event_id is None
    assert port.last_source_entity_type is None
    assert port.last_source_entity_id is None
    assert port.last_legacy_source_table is None
    assert port.last_legacy_source_id is None
    assert port.last_metadata is None


def test_happy_path_with_lineage_fields() -> None:
    """All optional lineage fields pass through to the port."""
    port = _StubPort()
    port.next_event = _event()

    record_lifecycle_event(
        port,
        animal_id="animal-id",
        event_type=LifecycleEventType.ADOPTION_STARTED,
        event_timestamp="2024-04-01T10:00:00+00:00",
        created_by="operator@apap.local",
        caused_by_event_id="00000000-0000-0000-0000-000000000050",
        source_entity_type="adopcion",
        source_entity_id="42",
        legacy_source_table="adopciones",
        legacy_source_id=123,
        metadata={"destino": "adoptante1"},
    )

    assert port.last_caused_by_event_id == "00000000-0000-0000-0000-000000000050"
    assert port.last_source_entity_type == "adopcion"
    assert port.last_source_entity_id == "42"
    assert port.last_legacy_source_table == "adopciones"
    assert port.last_legacy_source_id == 123
    assert port.last_metadata == {"destino": "adoptante1"}


def test_event_timestamp_accepts_datetime() -> None:
    """``datetime`` input flows through unchanged — the adapter normalises."""
    port = _StubPort()
    port.next_event = _event()

    when = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)

    record_lifecycle_event(
        port,
        animal_id="animal-id",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp=when,
        created_by="operator@apap.local",
    )

    assert port.last_event_timestamp is when


def test_blank_animal_id_raises_before_touching_port() -> None:
    """A blank ``animal_id`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_event = _event()

    for blank in ("", "   ", "\t\n"):
        with pytest.raises(LifecycleEventValidationError, match="animal_id"):
            record_lifecycle_event(
                port,
                animal_id=blank,
                event_type=LifecycleEventType.INTAKE_STARTED,
                event_timestamp="2024-03-01T10:00:00+00:00",
                created_by="operator@apap.local",
            )

    assert port.last_animal_id is None


def test_blank_created_by_raises_before_touching_port() -> None:
    """A blank ``created_by`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_event = _event()

    with pytest.raises(LifecycleEventValidationError, match="created_by"):
        record_lifecycle_event(
            port,
            animal_id="animal-id",
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp="2024-03-01T10:00:00+00:00",
            created_by="",
        )

    assert port.last_created_by is None


def test_none_animal_id_raises() -> None:
    """``None`` raises — the type system would catch this, but pin the contract."""
    port = _StubPort()

    with pytest.raises(LifecycleEventValidationError, match="animal_id"):
        record_lifecycle_event(
            port,
            animal_id=None,  # type: ignore[arg-type]
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp="2024-03-01T10:00:00+00:00",
            created_by="operator@apap.local",
        )

    assert port.last_animal_id is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(LifecycleEventValidationError, ValueError)


def test_enum_value_flows_through_unchanged() -> None:
    """The ``LifecycleEventType`` enum flows through to the port unchanged."""
    port = _StubPort()
    port.next_event = _event()

    record_lifecycle_event(
        port,
        animal_id="animal-id",
        event_type=LifecycleEventType.STATE_CORRECTION,
        event_timestamp="2024-03-01T10:00:00+00:00",
        created_by="operator@apap.local",
    )

    assert port.last_event_type is LifecycleEventType.STATE_CORRECTION
