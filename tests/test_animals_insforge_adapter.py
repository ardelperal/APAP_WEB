"""InsForge-adapter tests for the animals slice."""
from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from app.modules.animals.adapters.insforge import animals_insforge_photo
from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.adapters.insforge.animals_insforge_mappers import (
    _row_to_lifecycle_event,
)
from app.modules.animals.adapters.insforge.animals_insforge_photo import (
    PLACEHOLDER_PHOTO_PNG,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    get_animal_by_nchip_sql,
    get_animal_photo_meta_sql,
)
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.photo_service import (
    PLACEHOLDER_PHOTO_PNG as LEGACY_PLACEHOLDER_PHOTO_PNG,
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


class _FakePhotoClient(_FakeClient):
    def __init__(
        self,
        rows: list[dict[str, object]] | Exception,
        chunks: Iterator[bytes] | list[bytes] | Exception,
    ) -> None:
        super().__init__(rows)
        self._chunks = chunks
        self.storage_calls: list[tuple[str, str]] = []

    def download_object_stream(
        self, bucket: str, key: str
    ) -> Iterator[bytes]:
        self.storage_calls.append((bucket, key))
        if isinstance(self._chunks, Exception):
            raise self._chunks
        return iter(self._chunks)


def test_returns_none_when_no_match() -> None:
    """An empty result set yields ``None`` (not an exception)."""
    client = _FakeClient(rows=[])
    adapter = AnimalsInsforgeAdapter(
        client=client, storage=client  # type: ignore[arg-type]
    )
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
    adapter = AnimalsInsforgeAdapter(
        client=client, storage=client  # type: ignore[arg-type]
    )
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


@pytest.mark.parametrize(
    ("key", "expected_content_type"),
    [
        ("animals/luna.jpg", "image/jpeg"),
        ("animals/luna.unknown", "application/octet-stream"),
    ],
)
def test_resolve_photo_uses_real_insforge_download_boundary(
    key: str,
    expected_content_type: str,
) -> None:
    client = _FakePhotoClient(
        rows=[{"NombreFoto": key, "updated_at": "2026-08-23T10:00:00Z"}],
        chunks=[b"first", b"second"],
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    outcome = adapter.resolve_animal_photo("animal-1")

    assert outcome is not None
    assert outcome.is_placeholder is False
    assert outcome.media_type == expected_content_type
    assert outcome.content_length is None
    assert list(outcome.stream) == [b"first", b"second"]
    assert client.storage_calls == [("apap-photos", key)]
    assert client.last_query == get_animal_photo_meta_sql("animal-1")[0]
    assert client.last_params == ["animal-1"]


def test_resolved_stream_close_releases_partially_consumed_source() -> None:
    cleanup: list[str] = []

    def source() -> Iterator[bytes]:
        try:
            yield b"first"
            yield b"second"
        finally:
            cleanup.append("closed")

    client = _FakePhotoClient(
        rows=[{"NombreFoto": "animals/luna.jpg", "updated_at": None}],
        chunks=source(),
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)
    asset = adapter.resolve_animal_photo("animal-1")

    assert asset is not None
    assert next(asset.stream) == b"first"
    asset.stream.close()

    assert cleanup == ["closed"]
    with pytest.raises(StopIteration):
        next(asset.stream)


def test_resolved_stream_closes_source_when_iteration_raises() -> None:
    cleanup: list[str] = []

    def failing_source() -> Iterator[bytes]:
        try:
            yield b"first"
            raise RuntimeError("stream failed")
        finally:
            cleanup.append("closed")

    client = _FakePhotoClient(
        rows=[{"NombreFoto": "animals/luna.jpg", "updated_at": None}],
        chunks=failing_source(),
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)
    asset = adapter.resolve_animal_photo("animal-1")

    assert asset is not None
    assert next(asset.stream) == b"first"
    with pytest.raises(RuntimeError, match="stream failed"):
        next(asset.stream)

    assert cleanup == ["closed"]
    asset.stream.close()
    assert cleanup == ["closed"]


def test_animals_di_wires_insforge_client_as_photo_storage() -> None:
    client = _FakePhotoClient(
        rows=[
            {
                "NombreFoto": "animals/luna.png",
                "updated_at": "2026-08-23T10:00:00Z",
            }
        ],
        chunks=[b"png-bytes"],
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(insforge_client=client))
    )

    adapter = next(get_animals_port(request))  # type: ignore[arg-type]
    outcome = adapter.resolve_animal_photo("animal-1")

    assert outcome is not None
    assert outcome.is_placeholder is False
    assert list(outcome.stream) == [b"png-bytes"]
    assert client.storage_calls == [("apap-photos", "animals/luna.png")]


def test_resolve_photo_returns_none_only_for_unknown_animal() -> None:
    client = _FakePhotoClient(rows=[], chunks=[])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    assert adapter.resolve_animal_photo("missing") is None
    assert client.storage_calls == []


@pytest.mark.parametrize("missing_key", [None, "", "__missing__", 42])
def test_resolve_photo_uses_placeholder_without_storage_for_missing_key(
    missing_key: object,
) -> None:
    client = _FakePhotoClient(
        rows=[{"NombreFoto": missing_key, "updated_at": None}],
        chunks=[b"must-not-be-read"],
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    outcome = adapter.resolve_animal_photo("animal-1")

    assert outcome is not None
    assert outcome.is_placeholder is True
    assert list(outcome.stream) == [PLACEHOLDER_PHOTO_PNG]
    assert client.storage_calls == []


def test_resolve_photo_logs_sql_failure_without_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        animals_insforge_photo,
        "log_safe",
        lambda event, **fields: events.append((event, fields)),
    )
    client = _FakePhotoClient(rows=RuntimeError("secret"), chunks=[])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    outcome = adapter.resolve_animal_photo("private-animal-id")

    assert outcome is not None
    assert outcome.is_placeholder is True
    assert events == [
        ("animals.photo.sql_lookup_failed", {"reason": "RuntimeError"})
    ]


def test_resolve_photo_logs_storage_failure_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        animals_insforge_photo,
        "log_safe",
        lambda event, **fields: events.append((event, fields)),
    )
    client = _FakePhotoClient(
        rows=[{"NombreFoto": "private/key.jpg", "updated_at": None}],
        chunks=RuntimeError("secret"),
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    outcome = adapter.resolve_animal_photo("private-animal-id")

    assert outcome is not None
    assert outcome.is_placeholder is True
    assert events == [
        ("animals.photo.storage_failed", {"reason": "RuntimeError"})
    ]


def test_resolve_photo_treats_empty_storage_stream_as_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        animals_insforge_photo,
        "log_safe",
        lambda event, **fields: events.append((event, fields)),
    )
    client = _FakePhotoClient(
        rows=[{"NombreFoto": "empty.jpg", "updated_at": None}],
        chunks=[],
    )
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)

    outcome = adapter.resolve_animal_photo("animal-1")

    assert outcome is not None
    assert outcome.is_placeholder is True
    assert events == [("animals.photo.storage_empty", {})]


def test_placeholder_png_has_valid_chunks_crc_and_decodable_scanline() -> None:
    png = PLACEHOLDER_PHOTO_PNG
    assert png == LEGACY_PLACEHOLDER_PHOTO_PNG
    assert png.startswith(b"\x89PNG\r\n\x1a\n")

    offset = 8
    chunk_types: list[bytes] = []
    idat = bytearray()
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        chunk_type = png[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        data = png[data_start:data_end]
        stored_crc = struct.unpack(">I", png[data_end : data_end + 4])[0]
        assert stored_crc == zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        chunk_types.append(chunk_type)
        if chunk_type == b"IDAT":
            idat.extend(data)
        offset = data_end + 4

    assert offset == len(png)
    assert chunk_types == [b"IHDR", b"IDAT", b"IEND"]
    assert zlib.decompress(bytes(idat)) == b"\x01\x00\xff"
