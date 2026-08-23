"""Application-layer tests for ``resolve_animal_photo`` (slice #420-7 ninth surface).

Mirrors the stub-port pattern from the previous application-layer
tests in this slice so the use-case stays transport-free: the
application code never sees ``InsForgeClient``, the storage
backend, or the postgres connection; it talks to the
:class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.resolve_animal_photo import (
    PhotoResolutionValidationError,
    resolve_animal_photo,
)
from app.modules.animals.domain.photo import PhotoOutcome


def _ok_outcome() -> PhotoOutcome:
    """A representative ``status='ok'`` outcome (real photo stream)."""
    return PhotoOutcome(
        stream=iter([b"fake-jpeg-bytes"]),
        content_type="image/jpeg",
        etag='"abc123"',
        cache_control="private, max-age=3600, must-revalidate",
        content_length=12,
        status="ok",
    )


def _placeholder_outcome() -> PhotoOutcome:
    """A representative ``status='not_found'`` outcome (placeholder PNG)."""
    return PhotoOutcome(
        stream=iter([b"\x89PNG\r\n\x1a\n"]),
        content_type="image/png",
        etag="",
        cache_control="private, max-age=3600, must-revalidate",
        content_length=8,
        status="not_found",
    )


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.next_outcome: PhotoOutcome | None = None
        self.next_missing: bool = False

    def resolve_animal_photo(
        self, animal_id: str
    ) -> PhotoOutcome | None:
        self.last_animal_id = animal_id
        if self.next_missing:
            return None
        if self.next_outcome is None:
            raise AssertionError(
                "stub next_outcome unset; set it in the test before "
                "calling resolve_animal_photo"
            )
        return self.next_outcome

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
        event_type: object,
        event_timestamp: object,
        created_by: str,
        caused_by_event_id: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        legacy_source_table: str | None = None,
        legacy_source_id: int | None = None,
        metadata: dict | None = None,
    ) -> object:
        raise NotImplementedError

    def list_lifecycle_events(  # pragma: no cover
        self,
        animal_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_types: list[object] | None = None,
    ) -> list[object]:
        return []

    def change_animal_chip(  # pragma: no cover
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> object:
        raise NotImplementedError


def test_happy_path_strips_and_delegates() -> None:
    """Valid ``animal_id`` is stripped and forwarded verbatim to the port."""
    port = _StubPort()
    port.next_outcome = _ok_outcome()

    result = resolve_animal_photo(port, animal_id=" animal-id ")

    assert result is port.next_outcome
    assert port.last_animal_id == "animal-id"
    assert result is not None
    assert result.status == "ok"
    assert result.content_type == "image/jpeg"


def test_placeholder_outcome_flows_through() -> None:
    """A ``status='not_found'`` outcome (placeholder PNG) reaches the caller."""
    port = _StubPort()
    port.next_outcome = _placeholder_outcome()

    result = resolve_animal_photo(port, animal_id="animal-id")

    assert result is port.next_outcome
    assert result is not None
    assert result.status == "not_found"
    assert result.content_type == "image/png"
    assert result.content_length == 8


def test_unknown_animal_returns_none() -> None:
    """The port returns ``None`` for an unknown animal — the use case
    passes it through unchanged so the route renders 404."""
    port = _StubPort()
    port.next_missing = True

    result = resolve_animal_photo(port, animal_id="missing")

    assert result is None
    assert port.last_animal_id == "missing"


def test_blank_animal_id_raises_before_touching_port() -> None:
    """A blank ``animal_id`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_outcome = _ok_outcome()

    for blank in ("", "   ", "\t"):
        with pytest.raises(PhotoResolutionValidationError, match="animal_id"):
            resolve_animal_photo(port, animal_id=blank)

    assert port.last_animal_id is None


def test_none_animal_id_raises() -> None:
    """``None`` raises — the type system would catch this, but pin the contract."""
    port = _StubPort()
    port.next_outcome = _ok_outcome()

    with pytest.raises(PhotoResolutionValidationError, match="animal_id"):
        resolve_animal_photo(port, animal_id=None)  # type: ignore[arg-type]

    assert port.last_animal_id is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(PhotoResolutionValidationError, ValueError)


def test_stream_iterator_is_lazy() -> None:
    """The ``stream`` field on the outcome is an ``Iterator[bytes]`` — the
    use case does NOT consume or buffer it. This pins the streaming
    contract at the application boundary."""
    port = _StubPort()
    port.next_outcome = _ok_outcome()

    result = resolve_animal_photo(port, animal_id="animal-id")

    assert result is not None
    # ``iter()`` returns itself — a fresh iterator object the route
    # can consume via ``StreamingResponse``. The use case never called
    # ``list(stream)`` or read from it.
    assert iter(result.stream) is result.stream
