"""InsForge storage boundary for resolving transport-neutral photo assets."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    get_animal_photo_meta_sql,
)
from app.modules.animals.ports.photo_asset import PhotoAsset

PHOTO_BUCKET = "apap-photos"
PHOTO_SENTINEL_KEY = "__missing__"

# Valid 1x1 grayscale+alpha PNG. Every chunk CRC and the zlib-compressed
# scanline are pinned by the adapter tests.
PLACEHOLDER_PHOTO_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xf8\x0f\x00\x01\x05\x01"
    b"\x01'\x18\xe3f\x00\x00\x00\x00IEND\xaeB`\x82"
)

_CONTENT_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class PhotoStorageClient(Protocol):
    """Minimal real storage API required from ``InsForgeClient``."""

    def download_object_stream(
        self, bucket: str, key: str
    ) -> Iterator[bytes]: ...


class _PrependClosableIterator:
    """Prepend one inspected chunk and own the remaining source iterator."""

    def __init__(self, first_chunk: bytes, source: Iterator[bytes]) -> None:
        self._first_chunk = first_chunk
        self._source = source
        self._first_pending = True
        self._closed = False

    def __iter__(self) -> _PrependClosableIterator:
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        if self._first_pending:
            self._first_pending = False
            return self._first_chunk
        try:
            return next(self._source)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._source, "close", None)
        if callable(close):
            close()


def _placeholder() -> PhotoAsset:
    return PhotoAsset(
        stream=_PrependClosableIterator(PLACEHOLDER_PHOTO_PNG, iter(())),
        media_type="image/png",
        content_length=len(PLACEHOLDER_PHOTO_PNG),
        is_placeholder=True,
    )


def _content_type(key: str) -> str:
    lower_key = key.lower()
    return next(
        (
            content_type
            for suffix, content_type in _CONTENT_TYPES.items()
            if lower_key.endswith(suffix)
        ),
        "application/octet-stream",
    )


def _resolve_storage_stream(
    storage: PhotoStorageClient,
    *,
    key: str,
) -> PhotoAsset:
    try:
        stream = storage.download_object_stream(PHOTO_BUCKET, key)
        first_chunk = next(stream)
    except StopIteration:
        log_safe("animals.photo.storage_empty")
        return _placeholder()
    except Exception as exc:  # noqa: BLE001 — fail-closed storage boundary
        log_safe(
            "animals.photo.storage_failed",
            reason=type(exc).__name__,
        )
        return _placeholder()

    return PhotoAsset(
        stream=_PrependClosableIterator(first_chunk, stream),
        media_type=_content_type(key),
        content_length=None,
        is_placeholder=False,
    )


def resolve_animal_photo(
    client: SqlExecutor,
    storage: PhotoStorageClient,
    animal_id: str,
) -> PhotoAsset | None:
    """Resolve a real photo stream or the fail-closed placeholder."""
    try:
        rows = client.execute_sql(*get_animal_photo_meta_sql(animal_id))
    except Exception as exc:  # noqa: BLE001 — fail-closed SQL boundary
        log_safe(
            "animals.photo.sql_lookup_failed",
            reason=type(exc).__name__,
        )
        return _placeholder()

    if not rows:
        return None

    key = rows[0].get("NombreFoto")
    if not isinstance(key, str) or key in ("", PHOTO_SENTINEL_KEY):
        return _placeholder()

    return _resolve_storage_stream(
        storage,
        key=key,
    )


__all__ = [
    "PLACEHOLDER_PHOTO_PNG",
    "PhotoStorageClient",
    "resolve_animal_photo",
]
