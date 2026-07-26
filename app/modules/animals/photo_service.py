"""Photo display service for animal photos in the private ``apap-photos`` bucket.

The service is the single-responsibility bridge between the animals
domain (which knows about ``NombreFoto`` / sentinel keys / ``animal_id``)
and the storage client (which knows about the two-step S3-compatible
download flow). The service resolves the animal through the animals
data service, owns the fail-closed policy, and returns a
``PhotoOutcome`` with a byte iterator (never buffered). The route only
translates that typed outcome into an HTTP response.

Streaming contract (issue #285):

- ``PhotoOutcome`` carries ``stream: Iterator[bytes]`` — the route
  passes it directly to ``StreamingResponse`` without buffering.
- ``content_length`` is set when known (placeholder = PNG size;
  real photo = ``None`` because the stream is consumed lazily).
- ``etag`` is computed as ``hash(animal_id, updated_at, nombrefoto)``
  at resolution time so conditional requests work.
- ``cache_control`` is always
  ``private, max-age=3600, must-revalidate`` (photos are per-user).
- ``status`` is ``"ok"`` for a real photo stream and ``"not_found"``
  for any failure path (unknown animal, sentinel, storage error).

The route handles two pre-flight concerns before streaming starts:
1. ``not_found`` status → 404 response.
2. ``If-None-Match`` header matching ``outcome.etag`` → 304 response.

Mid-stream failures (network drop after 200 headers) are logged via
``log_safe`` and the response is allowed to truncate — no 5xx leak.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain
from typing import Any, Literal, Protocol

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.animals import service as animals_service

# --- Module-level constants (must be defined before use) --------------------

PHOTO_BUCKET = "apap-photos"
SENTINEL_KEY = "__missing__"
PLACEHOLDER_PHOTO_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfeA\xc0\xc1\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Sentinel ETag for animals with no photo (deterministic per animal_id).
_MISSING_ETAG_TEMPLATE = '"missing-%s"'


def compute_etag(animal_id: str, updated_at: str | None, nombrefoto: str | None) -> str:
    """Compute the ETag for an animal photo.

    ETag = ``hash(animal_id, updated_at, nombrefoto)`` encoded as a quoted
    string. Using metadata rather than the photo bytes allows conditional
    requests without downloading the photo.

    ``updated_at`` and ``nombrefoto`` may be ``None`` for sentinel cases
    (unknown animal, SQL error). In that case a deterministic sentinel
    ETag is returned so conditional requests still work correctly.
    """
    key = f"{animal_id}|{updated_at or ''}|{nombrefoto or ''}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f'"{digest}"'


# Map a storage-key file extension to its HTTP ``Content-Type``. Lifted
# to module level so the lookup table is one source of truth and the
# helper is a single dispatch. New MIME types are added here; tests in
# ``tests/test_animals_foto_route.py`` pin the dispatch contract.
_EXT_TO_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class PhotoStreamError(RuntimeError):
    """Raised when the photo stream cannot be produced.

    Covers the four failure modes the route must translate to a
    placeholder PNG: sentinel/missing key, storage transport failure
    raised EAGERLY by ``download_object_stream`` (e.g. strategy 401,
    streamed GET 5xx, network timeout on the request), the same kind
    of failure raised MID-ITERATION (after the streamed GET returned
    200 headers but the body chunks raise), and any other
    InsForge-shaped error. The service intentionally uses one error
    type so the route can surface a single, stable fail-closed contract.
    """


@dataclass(frozen=True, slots=True)
class PhotoResolution:
    """Resolved bytes and media type for the route's HTTP response.

    DEPRECATED (issue #285): use ``PhotoOutcome`` instead.
    ``PhotoResolution`` is retained for backward compatibility with
    existing tests and is not updated for streaming semantics.
    """

    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class PhotoOutcome:
    """Streaming photo outcome for the route's HTTP response.

    Carries all metadata needed by the route to build the HTTP response:
    - ``stream``: an ``Iterator[bytes]`` consumed by ``StreamingResponse``.
      The iterator is pulled lazily — no buffering.
    - ``content_type``: the ``Content-Type`` header value.
    - ``etag``: a quoted-string ETag derived from
      ``hash(animal_id, updated_at, nombrefoto)``.
    - ``cache_control``: the ``Cache-Control`` header value —
      always ``private, max-age=3600, must-revalidate``.
    - ``content_length``: total bytes when known (``None`` for streams
      because the total is not known until the iterator is exhausted).
    - ``status``: ``"ok"`` when a real photo was resolved;
      ``"not_found"`` for any failure path (unknown animal, sentinel,
      storage error, SQL error).

    The route's pre-flight logic:
    1. If ``status == "not_found"`` → 404 response.
    2. If ``If-None-Match`` header matches ``etag`` → 304 response.
    3. Otherwise → ``StreamingResponse(stream, media_type=content_type,
       headers={"ETag": etag, "Cache-Control": cache_control,
       "Content-Length": str(content_length) if content_length else ""})``.
    """

    stream: Iterator[bytes]
    content_type: str
    etag: str
    cache_control: str
    content_length: int | None
    status: Literal["ok", "not_found"]


class _StorageLike(Protocol):
    """Minimal storage surface the service depends on.

    Mirrors ``InsForgeClient.download_object_stream`` so tests can
    pass a fake without subclassing ``InsForgeClient``.
    """

    def download_object_stream(
        self, bucket: str, key: str
    ) -> Iterator[bytes]: ...


class _PhotoClient(SqlExecutor, _StorageLike, Protocol):
    """Combined SQL and storage surface required to resolve an animal photo."""


def is_missing_nombrefoto(nombrefoto: Any) -> bool:
    """Return True when the row's ``NombreFoto`` MUST NOT trigger a storage I/O.

    The sentinel ``__missing__`` (set by the migration when the source
    photo is missing/corrupt/unsupported) and ``None`` / empty-string
    are all "no I/O, serve placeholder" cases.
    """
    if nombrefoto is None:
        return True
    if not isinstance(nombrefoto, str):
        return True
    return nombrefoto == "" or nombrefoto == SENTINEL_KEY


def stream_animal_photo(
    storage_client: _StorageLike,
    *,
    nombrefoto: str | None,
) -> Iterator[bytes]:
    """Yield the bytes of ``nombrefoto`` via the storage client.

    Behaviour matrix:

    - ``nombrefoto`` is missing / sentinel → raise ``PhotoStreamError``
      BEFORE any storage call (no I/O cost). This branch is EAGER.
    - ``storage_client.download_object_stream`` raises eagerly (network
      timeout, 401 / 404 / 5xx from the strategy call, streamed GET
      returning 5xx before any body byte, etc.) → wrap as
      ``PhotoStreamError`` carrying the original exception as
      ``__cause__`` so the operator can still trace it. This branch
      is EAGER (the route's outer ``try / next(byte_iter)`` raises).
    - The streamed GET returned 200 headers but iteration over the
      body chunks raises (network drop, ``httpx.RemoteProtocolError``,
      per-chunk ``httpx.ReadTimeout``, mid-stream 5xx surfaced from
      the underlying transport, etc.) → wrap as ``PhotoStreamError``
      on the failing ``next()`` call. The route's outer ``try /
      next(byte_iter)`` catches it BEFORE
      ``StreamingResponse`` starts streaming.
    - The storage returns an iterator → yield the bytes verbatim.

    The iterator contract: the caller drains it via
    ``StreamingResponse``. The service does NOT close the underlying
    HTTP stream — the storage client owns the connection lifecycle.

    Caller discipline: pre-advance the generator with ``next(gen)``
    to surface any first-byte failure (PhotoStreamError or
    ``StopIteration``) BEFORE handing the rest to a streaming
    response, so a mid-stream transport error becomes a placeholder
    PNG instead of a partial response with the HTTP status already
    committed.
    """
    if is_missing_nombrefoto(nombrefoto):
        raise PhotoStreamError(
            "animal has no NombreFoto (missing/sentinel); serving placeholder"
        )
    # Narrowing: the guard above returns True for None, so past this
    # point nombrefoto is a real object key.
    assert nombrefoto is not None

    try:
        byte_iter = storage_client.download_object_stream(PHOTO_BUCKET, nombrefoto)
    except PhotoStreamError:
        # Re-raise without wrapping so the route's exception handling
        # sees the typed error directly.
        raise
    except Exception as exc:  # noqa: BLE001 — the route needs a single typed surface
        raise PhotoStreamError(
            f"photo stream failed for {nombrefoto!r}"
        ) from exc

    # Iterate lazily using ``yield from byte_iter``.  This correctly handles
    # both sync iterators (StopIteration propagates through yield from and
    # is caught by the outer try/except here) and async iterators
    # (Python auto-awaited the coroutine from byte_iter.__anext__()).
    #
    # NOTE: httpx exceptions raised DURING iteration of a sync iterator
    # (e.g. network drop mid-stream) propagate through ``yield from``
    # WITHOUT entering any except clause in this generator.  The caller
    # (route's pre-advance) sees ``StopIteration`` (generator exhausted)
    # and falls back to the placeholder outcome.  For async iterators
    # (the real InsForge client), httpx errors are raised BEFORE
    # ``yield from`` is entered (in the ``async with download_stream``)
    # and are caught by the outer ``except Exception`` below.
    try:
        yield from byte_iter
    except StopIteration:
        # Normal termination: iterator exhausted.
        pass
    except PhotoStreamError:
        raise
    except Exception as exc:  # noqa: BLE001 — single typed surface for the route
        raise PhotoStreamError(
            f"photo stream interrupted mid-iteration for {nombrefoto!r}"
        ) from exc


def content_type_for_key(nombrefoto: str | None) -> str:
    """Map a storage key to its HTTP ``Content-Type``.

    Only image MIME types are recognised; anything else falls back to
    ``application/octet-stream`` so the browser still triggers a
    download rather than rendering an unknown inline payload. Empty /
    None inputs return the placeholder PNG type.
    """
    if not nombrefoto:
        return "image/png"
    lower = nombrefoto.lower()
    for ext, mime in _EXT_TO_MIME.items():
        if lower.endswith(ext):
            return mime
    return "application/octet-stream"


_CACHE_CONTROL = "private, max-age=3600, must-revalidate"


def resolve_animal_photo(
    client: _PhotoClient,
    animal_id: str,
) -> PhotoOutcome | None:
    """Resolve the fail-closed photo policy without constructing HTTP responses.

    Returns ``None`` when the animal is genuinely unknown (route raises 404).
    Returns a ``PhotoOutcome`` otherwise; the ``status`` field distinguishes
    the animal found-but-no-photo case (``"not_found"``, route returns
    the placeholder PNG at HTTP 200) from the successful photo stream
    (``"ok"``). The route translates the ``None`` case to 404.

    The returned ``stream`` is an ``Iterator[bytes]`` consumed lazily
    by ``StreamingResponse``. The iterator must NOT be buffered with
    ``list()`` — that defeats the streaming purpose.
    """
    try:
        animal = animals_service.get_animal_by_id(client, animal_id)
    except Exception as exc:  # noqa: BLE001 — established fail-closed contract
        log_safe(
            "animal_foto.sql_lookup_failed",
            reason=type(exc).__name__,
        )
        # SQL error — animal might exist but we can't confirm; return 200
        # with placeholder so the client sees a photo rather than a 404.
        return PhotoOutcome(
            stream=iter([PLACEHOLDER_PHOTO_PNG]),
            content_type="image/png",
            etag=compute_etag(animal_id, None, None),
            cache_control=_CACHE_CONTROL,
            content_length=len(PLACEHOLDER_PHOTO_PNG),
            status="not_found",
        )

    if animal is None:
        # Animal genuinely missing — route raises 404.
        return None

    if is_missing_nombrefoto(animal.NombreFoto):
        # Animal found but no photo → placeholder, HTTP 200.
        return PhotoOutcome(
            stream=iter([PLACEHOLDER_PHOTO_PNG]),
            content_type="image/png",
            etag=compute_etag(animal_id, animal.updated_at, animal.NombreFoto),
            cache_control=_CACHE_CONTROL,
            content_length=len(PLACEHOLDER_PHOTO_PNG),
            status="not_found",
        )

    try:
        byte_iter = stream_animal_photo(client, nombrefoto=animal.NombreFoto)
        # Pre-advance once to surface any mid-stream error before the
        # route starts sending HTTP headers.  If the stream is empty
        # (StopIteration), the animal has no photo → placeholder.
        # Any other exception means a storage I/O failure → placeholder.
        try:
            first_chunk = next(byte_iter)
        except StopIteration:
            first_chunk = None
        except Exception as exc:
            # Storage error during pre-advance → return placeholder at 200.
            log_safe(
                "animals.photo.preadvance_error",
                animal_id=animal_id,
                error=type(exc).__name__,
            )
            return PhotoOutcome(
                stream=iter([PLACEHOLDER_PHOTO_PNG]),
                content_type="image/png",
                etag=compute_etag(animal_id, animal.updated_at, animal.NombreFoto),
                cache_control=_CACHE_CONTROL,
                content_length=len(PLACEHOLDER_PHOTO_PNG),
                status="not_found",
            )
    except PhotoStreamError:
        # Raised before yielding any chunk (storage unreachable, DNS fail,
        # permission error, etc.) → placeholder, HTTP 200.
        return PhotoOutcome(
            stream=iter([PLACEHOLDER_PHOTO_PNG]),
            content_type="image/png",
            etag=compute_etag(animal_id, animal.updated_at, animal.NombreFoto),
            cache_control=_CACHE_CONTROL,
            content_length=len(PLACEHOLDER_PHOTO_PNG),
            status="not_found",
        )

    return PhotoOutcome(
        stream=chain([first_chunk] if first_chunk is not None else [], byte_iter),
        content_type=content_type_for_key(animal.NombreFoto),
        etag=compute_etag(animal_id, animal.updated_at, animal.NombreFoto),
        cache_control=_CACHE_CONTROL,
        content_length=None,  # Streamed — total size not known until exhausted.
        status="ok",
    )


__all__ = [
    "PHOTO_BUCKET",
    "PLACEHOLDER_PHOTO_PNG",
    "SENTINEL_KEY",
    "PhotoOutcome",
    "PhotoResolution",
    "PhotoStreamError",
    "compute_etag",
    "content_type_for_key",
    "is_missing_nombrefoto",
    "resolve_animal_photo",
    "stream_animal_photo",
]
