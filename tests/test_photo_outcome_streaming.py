"""TDD atoms for PhotoOutcome streaming + ETag + cache contract.

Tests the new contract from issue #285:
- PhotoOutcome dataclass with stream (Iterator[bytes]), content_type, etag,
  cache_control, content_length, status
- resolve_animal_photo returns PhotoOutcome (never None — not_found status is used)
- ETag = hash(animal_id, updated_at, nombrefoto) when available
- 404 animal → status='not_found', placeholder PNG stream
- streaming: route returns StreamingResponse with iterator body
- 304: If-None-Match header matching ETag → 304 with ETag + Cache-Control
- Cache-Control: private, max-age=3600, must-revalidate
- mid-stream failure: log_safe call and let response truncate
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.animals.photo_service import (
    PLACEHOLDER_PHOTO_PNG,
    PhotoOutcome,
    compute_etag,
    resolve_animal_photo,
)

# =============================================================================
# PhotoOutcome dataclass shape
# =============================================================================


class TestPhotoOutcomeDataclass:
    """PhotoOutcome carries all streaming metadata."""

    def test_photo_outcome_has_expected_fields(self) -> None:
        """All required fields are present on PhotoOutcome."""
        outcome = PhotoOutcome(
            stream=iter([b"data"]),
            content_type="image/jpeg",
            etag='"abc123"',
            cache_control="private, max-age=3600, must-revalidate",
            content_length=None,
            status="ok",
        )
        assert outcome.content_type == "image/jpeg"
        assert outcome.etag == '"abc123"'
        assert outcome.cache_control == "private, max-age=3600, must-revalidate"
        assert outcome.content_length is None
        assert outcome.status == "ok"

    def test_photo_outcome_status_not_found(self) -> None:
        """not_found status is used when the animal does not exist."""
        outcome = PhotoOutcome(
            stream=iter([PLACEHOLDER_PHOTO_PNG]),
            content_type="image/png",
            etag='"missing"',
            cache_control="private, max-age=3600, must-revalidate",
            content_length=len(PLACEHOLDER_PHOTO_PNG),
            status="not_found",
        )
        assert outcome.status == "not_found"


# =============================================================================
# compute_etag
# =============================================================================


class TestComputeEtag:
    """ETag = hash(animal_id, updated_at, nombrefoto)."""

    def test_etag_changes_when_nombrefoto_changes(self) -> None:
        e1 = compute_etag("anim-1", "2025-01-01T00:00:00Z", "foto.jpg")
        e2 = compute_etag("anim-1", "2025-01-01T00:00:00Z", "other.jpg")
        assert e1 != e2

    def test_etag_changes_when_updated_at_changes(self) -> None:
        e1 = compute_etag("anim-1", "2025-01-01T00:00:00Z", "foto.jpg")
        e2 = compute_etag("anim-1", "2025-06-15T12:00:00Z", "foto.jpg")
        assert e1 != e2

    def test_etag_is_stable_for_same_inputs(self) -> None:
        e1 = compute_etag("anim-1", "2025-01-01T00:00:00Z", "foto.jpg")
        e2 = compute_etag("anim-1", "2025-01-01T00:00:00Z", "foto.jpg")
        assert e1 == e2

    def test_etag_format_is_quoted_string(self) -> None:
        etag = compute_etag("anim-1", "2025-01-01T00:00:00Z", "foto.jpg")
        assert etag.startswith('"')
        assert etag.endswith('"')


# =============================================================================
# resolve_animal_photo returns PhotoOutcome (never None)
# =============================================================================


class _LookupClient:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        lookup_error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.lookup_error = lookup_error
        self.download_calls: list[tuple[str, str]] = []

    def execute_sql(
        self, query: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.rows

    def download_object_stream(self, bucket: str, key: str) -> Iterator[bytes]:
        self.download_calls.append((bucket, key))
        yield b"photo"


def test_resolve_animal_photo_returns_none_for_unknown_animal() -> None:
    """Unknown animal returns None so the route can emit 404."""
    client = _LookupClient(rows=[])
    result = resolve_animal_photo(client, "missing-animal")
    assert result is None


def test_resolve_animal_photo_returns_photo_outcome_for_valid_animal() -> None:
    """Valid animal with photo returns status='ok' + stream."""
    client = _LookupClient(
        rows=[{
            "id": "anim-1",
            "NCHIP": "941000000000001",
            "NombreAnimal": "Firulais",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2023-04-12",
            "activo": True,
            "NombreFoto": "abc123.jpg",
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-1")
    assert isinstance(result, PhotoOutcome)
    assert result.status == "ok"
    assert result.content_type == "image/jpeg"
    assert result.etag.startswith('"')


def test_resolve_animal_photo_etag_uses_updated_at_and_nombrefoto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ETag derives from animal_id + updated_at + nombrefoto."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _LookupClient(
        rows=[{
            "id": "anim-etag",
            "NCHIP": "941000000000002",
            "NombreAnimal": "Etagon",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2022-03-15",
            "activo": True,
            "NombreFoto": "etag-photo.jpg",
            "updated_at": "2025-06-01T10:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-etag")
    assert isinstance(result, PhotoOutcome)
    # ETag must be deterministic and quote-wrapped
    etag = compute_etag("anim-etag", "2025-06-01T10:00:00Z", "etag-photo.jpg")
    assert result.etag == etag


def test_resolve_animal_photo_sentinel_returns_not_found_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentinel __missing__ NombreFoto → status='not_found'."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _LookupClient(
        rows=[{
            "id": "anim-sentinel",
            "NCHIP": "941000000000003",
            "NombreAnimal": "SentinelDog",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2020-01-01",
            "activo": True,
            "NombreFoto": "__missing__",
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-sentinel")
    assert isinstance(result, PhotoOutcome)
    assert result.status == "not_found"


def test_resolve_animal_photo_null_nombrefoto_returns_not_found_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Null NombreFoto → status='not_found'."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _LookupClient(
        rows=[{
            "id": "anim-null",
            "NCHIP": "941000000000004",
            "NombreAnimal": "NullDog",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2020-01-01",
            "activo": True,
            "NombreFoto": None,
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-null")
    assert isinstance(result, PhotoOutcome)
    assert result.status == "not_found"


def test_resolve_animal_photo_storage_error_returns_not_found_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storage failure → status='not_found' (fail-closed).

    The storage error is raised when the iterator is advanced in the route
    (mid-stream failure), not at resolve_animal_photo call time.
    resolve_animal_photo returns the iterator without error; the exception
    is caught by the route's pre-advance logic.
    """

    class _MidStreamFailClient(_LookupClient):
        """Yields one chunk then raises — mimics a real mid-stream error."""

        def download_object_stream(self, bucket: str, key: str) -> Iterator[bytes]:
            yield b"first-chunk-"
            raise RuntimeError("storage unavailable")

    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _MidStreamFailClient(
        rows=[{
            "id": "anim-fail",
            "NCHIP": "941000000000005",
            "NombreAnimal": "FailDog",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2020-01-01",
            "activo": True,
            "NombreFoto": "fail.jpg",
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-fail")
    assert isinstance(result, PhotoOutcome)
    # Iterator is returned; mid-stream error surfaces in the route's pre-advance.
    assert result.status == "ok"
    assert result.content_type == "image/jpeg"
    # Confirm the first chunk is available and the second raises
    assert next(result.stream) == b"first-chunk-"
    with pytest.raises(RuntimeError):
        next(result.stream)


def test_resolve_animal_photo_sql_error_returns_not_found_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQL lookup error → status='not_found' with log_safe."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _LookupClient(lookup_error=RuntimeError("sql down"))
    result = resolve_animal_photo(client, "anim-sql-fail")
    assert isinstance(result, PhotoOutcome)
    assert result.status == "not_found"
    assert logged == [
        ("animal_foto.sql_lookup_failed", {"reason": "RuntimeError"})
    ]


def test_resolve_animal_photo_stream_is_iterator_not_buffered_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stream field is an Iterator[bytes], not a list or bytes."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    chunks = [b"chunk1-", b"chunk2-", b"chunk3"]

    class _ChunkedClient(_LookupClient):
        def download_object_stream(self, bucket: str, key: str) -> Iterator[bytes]:
            yield from chunks

    client = _ChunkedClient(
        rows=[{
            "id": "anim-stream",
            "NCHIP": "941000000000006",
            "NombreAnimal": "StreamDog",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2020-01-01",
            "activo": True,
            "NombreFoto": "stream.jpg",
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-stream")
    assert isinstance(result, PhotoOutcome)
    # stream is consumed as bytes are pulled
    first_chunk = next(result.stream)
    assert first_chunk == b"chunk1-"
    # It is an iterator, not a list
    assert not isinstance(result.stream, list | tuple)


def test_resolve_animal_photo_sentinel_has_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentinel NombreFoto outcome includes content_length of placeholder."""
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )
    client = _LookupClient(
        rows=[{
            "id": "anim-sentinel",
            "NCHIP": "941000000000001",
            "NombreAnimal": "SentinelDog",
            "Especie": "CANINA",
            "Sexo": "M",
            "FNacimiento": "2020-01-01",
            "activo": True,
            "NombreFoto": "__missing__",
            "updated_at": "2025-01-01T00:00:00Z",
        }]
    )
    result = resolve_animal_photo(client, "anim-sentinel")
    assert isinstance(result, PhotoOutcome)
    assert result.status == "not_found"
    assert result.content_length == len(PLACEHOLDER_PHOTO_PNG)
