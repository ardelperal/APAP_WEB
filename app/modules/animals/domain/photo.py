"""Domain result type for the animal-photo streaming resolver (issue #285).

``PhotoOutcome`` is the hexagonal projection of the legacy
:class:`app.modules.animals.photo_service.PhotoOutcome`. The
adapter returns one of these from
:meth:`AnimalsPort.resolve_animal_photo` and the route layer
translates it into an HTTP response — ``not_found`` becomes 404,
a matching ``If-None-Match`` becomes 304, otherwise a streaming 200.

The ``stream`` field is an :class:`Iterator[bytes]` consumed lazily by
the route's ``StreamingResponse``; the adapter must NOT buffer the
iterator with ``list()`` because that defeats the streaming purpose.
``content_length`` is ``None`` for real photos because the total
is unknown until the iterator is exhausted; it is set for the
placeholder PNG because the bytes are constant.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class PhotoOutcome:
    """Streaming photo outcome for the route's HTTP response.

    Carries all metadata needed by the route to build the HTTP
    response:

    - ``stream``: an ``Iterator[bytes]`` consumed by
      ``StreamingResponse``. The iterator is pulled lazily — no
      buffering.
    - ``content_type``: the ``Content-Type`` header value.
    - ``etag``: a quoted-string ETag derived from
      ``hash(animal_id, updated_at, nombrefoto)``.
    - ``cache_control``: the ``Cache-Control`` header value —
      always ``private, max-age=3600, must-revalidate``.
    - ``content_length``: total bytes when known (``None`` for
      streams because the total is not known until the iterator
      is exhausted).
    - ``status``: ``"ok"`` when a real photo was resolved;
      ``"not_found"`` for any failure path (unknown animal,
      sentinel, storage error, SQL error).
    """

    stream: Iterator[bytes]
    content_type: str
    etag: str
    cache_control: str
    content_length: int | None
    status: Literal["ok", "not_found"]


__all__ = ["PhotoOutcome"]
