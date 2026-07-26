"""Service-level contract for resolving animal-photo outcomes."""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.animals.photo_service import (
    PLACEHOLDER_PHOTO_PNG,
    PhotoOutcome,
    resolve_animal_photo,
)


class _LookupClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.lookup_error: Exception | None = None

    def execute_sql(
        self, query: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.rows

    def download_object_stream(self, bucket: str, key: str):
        yield b"photo"


def test_resolve_animal_photo_returns_none_for_unknown_animal() -> None:
    assert resolve_animal_photo(_LookupClient(), "missing") is None


def test_resolve_animal_photo_fails_closed_on_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _LookupClient()
    client.lookup_error = RuntimeError("lookup failed")
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.modules.animals.photo_service.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )

    result = resolve_animal_photo(client, "animal-1")

    assert isinstance(result, PhotoOutcome)
    assert result.status == "not_found"
    assert result.content_type == "image/png"
    assert result.content_length == len(PLACEHOLDER_PHOTO_PNG)
    assert logged == [
        ("animal_foto.sql_lookup_failed", {"reason": "RuntimeError"})
    ]
