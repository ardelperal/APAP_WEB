"""Transport-neutral photo asset contract for the animals port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ClosableBytesIterator(Protocol):
    """Owned byte stream that callers must close after consumption."""

    def __iter__(self) -> ClosableBytesIterator: ...

    def __next__(self) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PhotoAsset:
    """Resolved photo bytes and intrinsic asset metadata.

    ``stream`` owns the underlying storage resource. The consumer must
    call ``close()`` in deterministic cleanup, including cancellation and
    partial-consumption paths.
    """

    stream: ClosableBytesIterator
    media_type: str
    content_length: int | None
    is_placeholder: bool


__all__ = ["ClosableBytesIterator", "PhotoAsset"]
