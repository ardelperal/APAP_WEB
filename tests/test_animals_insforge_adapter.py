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
from app.modules.animals.adapters.insforge.animals_insforge_chip_cascade import (
    AnimalsInsforgeChipCascade,
)
from app.modules.animals.adapters.insforge.animals_insforge_mappers import (
    _row_to_animal,
    _row_to_lifecycle_event,
)
from app.modules.animals.adapters.insforge.animals_insforge_photo import (
    PLACEHOLDER_PHOTO_PNG,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    GET_ANIMAL_BY_ID_SQL,
    get_animal_by_nchip_sql,
    get_animal_photo_meta_sql,
    list_animals_sql,
)
from app.modules.animals.di.animals_di import get_animals_port
from app.modules.animals.domain.animal import (
    Animal,
    AnimalSearchResult,
    Especie,
    Sexo,
)
from app.modules.animals.domain.change_chip_result import ChangeChipResult
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


class _SequencedFakeClient:
    """SQL fake returning one configured response per call."""

    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, list[object] | None]] = []

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, params))
        return next(self._responses)


def _animal_row(index: int) -> dict[str, object]:
    """Build one valid seven-field animal transport row."""
    return {
        "id": f"animal-{index}",
        "NCHIP": f"94100000000000{index}",
        "NombreAnimal": f"Animal {index}",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2024-03-01",
        "activo": True,
    }


_WIDENED_FIELDS = (
    "fecha_alta", "estado", "TraeNChip", "FIMPLANTACIONCHIP", "Raza",
    "Color", "Pelo", "Tamano", "Caracter", "FDefuncion", "Terapia",
    "Observaciones", "NombreFoto", "Cartilla", "Eutanasia", "RazaPPP",
    "Mestizo", "EutanasiaOtrasCausas", "EutanasiaEnfermedad",
    "UltimoEstadoAntesDeFallecido", "ComunicacionARIAC",
)


def test_row_to_animal_maps_the_full_28_field_shape() -> None:
    row = {
        **_animal_row(1),
        "fecha_alta": "2026-08-25T10:00:00Z",
        "current_state": "Albergue",
        "TraeNChip": "Si",
        "FIMPLANTACIONCHIP": "2024-03-02",
        "Raza": "Mestiza",
        "Color": "Negro",
        "Pelo": "Corto",
        "Tamano": "Mediano",
        "Caracter": "Sociable",
        "FDefuncion": "",
        "Terapia": "No",
        "Observaciones": "Sin observaciones",
        "NombreFoto": "animals/luna.jpg",
        "Cartilla": "Si",
        "Eutanasia": "No",
        "RazaPPP": "No",
        "Mestizo": "Si",
        "EutanasiaOtrasCausas": "No",
        "EutanasiaEnfermedad": "No",
        "UltimoEstadoAntesDeFallecido": "Albergue",
        "ComunicacionARIAC": "Si",
    }

    animal = _row_to_animal(row)

    expected = {
        name: "albergue" if name == "estado" else row[name]
        for name in _WIDENED_FIELDS
    }
    actual = {name: getattr(animal, name) for name in _WIDENED_FIELDS}
    assert actual == expected, "the mapper must preserve every widened transport value"


def test_row_to_animal_accepts_the_original_partial_row() -> None:
    animal = _row_to_animal(_animal_row(1))

    for name in _WIDENED_FIELDS:
        assert getattr(animal, name) is None, f"missing {name} must map to None"


def test_row_to_animal_reads_estado_from_current_state() -> None:
    animal = _row_to_animal({**_animal_row(1), "current_state": "Acogida"})
    assert animal.estado == "acogida", (
        "estado must normalize the current_state database label for the API"
    )


def test_list_animals_sql_restores_legacy_order_with_stable_tiebreaker() -> None:
    sql, params = list_animals_sql(limit=50, offset=0, activo_only=True)

    assert 'ORDER BY fecha_alta DESC, "NCHIP" ASC' in sql, (
        "list pagination must be newest-first and deterministic for equal timestamps"
    )
    assert params == ["50", "0"], "list pagination binds must remain unchanged"


def test_get_animal_by_id_returns_row_when_exists() -> None:
    client = _FakeClient(rows=[_animal_row(1)])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    result = adapter.get_animal_by_id("animal-1")

    assert result == Animal(
        id="animal-1",
        NCHIP="941000000000001",
        NombreAnimal="Animal 1",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    ), "primary-key lookup must map the returned row"
    assert client.last_query == GET_ANIMAL_BY_ID_SQL, "lookup must use the query seam"
    assert client.last_params == ["animal-1"], "lookup must bind the primary key"


def test_get_animal_by_id_returns_none_when_missing() -> None:
    client = _FakeClient(rows=[])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    assert adapter.get_animal_by_id("missing") is None, "missing ids must return None"


def test_get_animal_by_id_projects_every_edit_form_column() -> None:
    for column in _WIDENED_FIELDS:
        if column == "estado":
            continue
        sql_column = column if column == "fecha_alta" else f'"{column}"'
        assert sql_column in GET_ANIMAL_BY_ID_SQL, (
            f"primary-key lookup must project {column} for edit prefill"
        )


def test_search_animals_projects_current_state_without_state_filter() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals()

    sql = client.calls[0][0]
    assert "acs.current_state" in sql, "search rows must project the derived state"
    assert "LEFT JOIN animal_current_state" in sql, (
        "search must join state even when estado is not a filter"
    )


def test_search_animals_no_filters_returns_data_and_total() -> None:
    rows = [_animal_row(index) for index in range(1, 4)]
    client = _SequencedFakeClient([rows, [{"total": 3}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    result = adapter.search_animals()

    assert isinstance(result, AnimalSearchResult), "search must return the domain envelope"
    assert result.data == tuple(
        Animal(
            id=f"animal-{index}",
            NCHIP=f"94100000000000{index}",
            NombreAnimal=f"Animal {index}",
            Especie=Especie.CANINA,
            Sexo=Sexo.H,
            FNacimiento="2024-03-01",
        )
        for index in range(1, 4)
    ), "all rows must be mapped in order"
    assert result.total == 3, "total must come from the count query"
    assert result.limit == 50, "default limit must be preserved"
    assert result.offset == 0, "default offset must be preserved"


def test_search_animals_with_chip_filter_sends_param() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals(chip="941000000000001")

    sql, params = client.calls[0]
    assert 'a."NCHIP" = $1' in sql, "chip must use an exact-match WHERE clause"
    assert params == ["941000000000001", 50, 0], "chip must be the first bind"


def test_search_animals_with_q_filter_sends_like_param() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals(q="Luna")

    sql, params = client.calls[0]
    assert 'a."NombreAnimal" ILIKE $1' in sql, "q must filter animal names"
    assert params == ["%Luna%", 50, 0], "q must be wrapped for substring matching"


def test_search_animals_with_estado_filter_uses_join() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals(estado="acogida")

    sql, params = client.calls[0]
    assert "LEFT JOIN animal_current_state" in sql, "estado requires the state join"
    assert "acs.current_state = $1" in sql, "estado must filter the derived state"
    assert params == ["Acogida", 50, 0], "estado must bind its database label"


def test_search_animals_forwards_enum_and_date_filters() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals(
        especie=Especie.FELINA,
        sexo=Sexo.M,
        fecha_alta_since="2026-01-01",
        fecha_alta_until="2026-12-31",
    )

    sql, params = client.calls[0]
    assert 'a."Especie" = $1' in sql, "species must use an exact match"
    assert 'a."Sexo" = $2' in sql, "sex must use an exact match"
    assert "a.fecha_alta >= $3" in sql, "the lower date bound must be inclusive"
    assert "a.fecha_alta <= $4" in sql, "the upper date bound must be inclusive"
    assert params == ["FELINA", "M", "2026-01-01", "2026-12-31", 50, 0], (
        "domain enums and date bounds must be bound in declaration order"
    )


def test_search_animals_pagination() -> None:
    client = _SequencedFakeClient([[], [{"total": 0}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    adapter.search_animals(limit=10, offset=20)

    search_sql, search_params = client.calls[0]
    count_sql, count_params = client.calls[1]
    assert "LIMIT $1 OFFSET $2" in search_sql, "data query must paginate"
    assert search_params == [10, 20], "pagination binds must preserve values"
    assert "LIMIT" not in count_sql, "count query must not paginate"
    assert "OFFSET" not in count_sql, "count query must not offset"
    assert count_params == [], "count query must omit pagination binds"


def test_search_animals_total_independent_of_limit() -> None:
    rows = [_animal_row(index) for index in range(1, 11)]
    client = _SequencedFakeClient([rows, [{"total": 42}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    result = adapter.search_animals(limit=10)

    assert len(result.data) == 10, "data must contain only the requested page"
    assert result.total == 42, "total must be independent of page size"


def test_search_animals_zero_limit_executes_only_count_query() -> None:
    client = _SequencedFakeClient([[{"total": 42}]])
    adapter = AnimalsInsforgeAdapter(client=client, storage=client)  # type: ignore[arg-type]

    result = adapter.search_animals(limit=0, offset=10)

    assert result.data == (), "count-only search must not return data"
    assert result.total == 42, "count-only search must return the fresh total"
    assert result.limit == 0, "count-only envelope must preserve limit zero"
    assert result.offset == 10, "count-only envelope must preserve the cursor"
    assert len(client.calls) == 1, "count-only search must skip the data query"
    assert "COUNT(*)" in client.calls[0][0], "the only query must be the count"


def test_extracted_chip_cascade_matches_adapter_duplicate_chip_result() -> None:
    cascade_client = _SequencedFakeClient([[{"id": "animal-2"}]])
    adapter_client = _SequencedFakeClient([[{"id": "animal-2"}]])
    cascade = AnimalsInsforgeChipCascade(cascade_client)
    adapter = AnimalsInsforgeAdapter(
        client=adapter_client,
        storage=adapter_client,  # type: ignore[arg-type]
    )
    kwargs = {
        "animal_id": "animal-1",
        "old_chip": "old-chip",
        "new_chip": "duplicate-chip",
        "reason": "data correction",
        "operador_user_id": "operator-1",
    }

    cascade_result = cascade.change_animal_chip(**kwargs)
    adapter_result = adapter.change_animal_chip(**kwargs)

    assert isinstance(cascade_result, ChangeChipResult), (
        "the extracted cascade must preserve the port return type"
    )
    assert cascade_result == adapter_result, (
        "adapter delegation must preserve duplicate-chip behavior"
    )


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
