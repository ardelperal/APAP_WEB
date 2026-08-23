"""Application-layer tests for ``list_lifecycle_events`` (slice #420-7 seventh surface).

Mirrors the stub-port pattern from the previous application-layer
tests in this slice so the use-case stays transport-free: the
application code never sees ``InsForgeClient`` or ``SqlExecutor``;
it talks to the :class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.list_lifecycle_events import (
    MAX_PAGE_SIZE,
    LifecycleListValidationError,
    list_lifecycle_events,
)
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.last_limit: int | None = None
        self.last_offset: int | None = None
        self.last_event_types: list[LifecycleEventType] | None = None
        self.next_events: list[AnimalLifecycleEvent] = []

    def list_lifecycle_events(
        self,
        animal_id: str,
        *,
        limit: int,
        offset: int,
        event_types: list[LifecycleEventType] | None,
    ) -> list[AnimalLifecycleEvent]:
        self.last_animal_id = animal_id
        self.last_limit = limit
        self.last_offset = offset
        self.last_event_types = event_types
        return self.next_events

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

    def record_lifecycle_event(  # pragma: no cover
        self,
        *,
        animal_id: str,
        event_type: LifecycleEventType,
        event_timestamp: object,
        created_by: str,
        caused_by_event_id: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        legacy_source_table: str | None = None,
        legacy_source_id: int | None = None,
        metadata: dict | None = None,
    ) -> AnimalLifecycleEvent:
        raise NotImplementedError


def _event(idx: int) -> AnimalLifecycleEvent:
    return AnimalLifecycleEvent(
        id=f"00000000-0000-0000-0000-{idx:012d}",
        animal_id="00000000-0000-0000-0000-000000000042",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp=f"2024-03-{idx + 1:02d}T10:00:00+00:00",
        created_by="operator@apap.local",
    )


def test_default_call_passes_through() -> None:
    """Default kwargs (limit=50, offset=0, no filter) reach the port."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id="animal-id")

    assert port.last_animal_id == "animal-id"
    assert port.last_limit == 50
    assert port.last_offset == 0
    assert port.last_event_types is None


def test_animal_id_is_stripped() -> None:
    """Whitespace around ``animal_id`` is stripped before delegation."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id=" animal-id ")

    assert port.last_animal_id == "animal-id"


def test_event_types_pass_through_unchanged() -> None:
    """The ``event_types`` filter list flows through verbatim."""
    port = _StubPort()

    list_lifecycle_events(
        port,
        animal_id="animal-id",
        event_types=[
            LifecycleEventType.INTAKE_STARTED,
            LifecycleEventType.ADOPTION_STARTED,
        ],
    )

    assert port.last_event_types == [
        LifecycleEventType.INTAKE_STARTED,
        LifecycleEventType.ADOPTION_STARTED,
    ]


def test_results_returned_unchanged() -> None:
    """The use case does not decorate the port's output."""
    port = _StubPort()
    port.next_events = [_event(1), _event(2)]

    result = list_lifecycle_events(port, animal_id="animal-id")

    assert result == port.next_events


def test_negative_limit_clamps_to_one() -> None:
    """``limit=-1`` clamps to 1 — the SQL ``LIMIT`` clause needs ``>= 1``."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id="id", limit=-7)

    assert port.last_limit == 1


def test_oversized_limit_clamps_to_max_page_size() -> None:
    """``limit > MAX_PAGE_SIZE`` clamps to the cap so a misconfigured caller
    can't pull the whole timeline in one shot."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id="id", limit=MAX_PAGE_SIZE + 500)

    assert port.last_limit == MAX_PAGE_SIZE


def test_negative_offset_clamps_to_zero() -> None:
    """``offset=-1`` clamps to 0 — postgres rejects ``OFFSET -1``."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id="id", offset=-3)

    assert port.last_offset == 0


def test_blank_animal_id_raises_before_touching_port() -> None:
    """A blank ``animal_id`` short-circuits before the port sees anything."""
    port = _StubPort()

    for blank in ("", "   ", "\t\n"):
        with pytest.raises(LifecycleListValidationError, match="animal_id"):
            list_lifecycle_events(port, animal_id=blank)

    assert port.last_animal_id is None


def test_none_animal_id_raises() -> None:
    """``None`` raises — the type system would catch this, but pin the contract."""
    port = _StubPort()

    with pytest.raises(LifecycleListValidationError, match="animal_id"):
        list_lifecycle_events(port, animal_id=None)  # type: ignore[arg-type]

    assert port.last_animal_id is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(LifecycleListValidationError, ValueError)


def test_empty_event_types_is_same_as_none() -> None:
    """``event_types=[]`` flows through as-is — the adapter's empty-list
    short-circuit to the no-filter path is the SQL-level concern."""
    port = _StubPort()

    list_lifecycle_events(port, animal_id="animal-id", event_types=[])

    assert port.last_event_types == []
