"""Photo display service for animal photos in the private ``apap-photos`` bucket.

The service is the single-responsibility bridge between the animals
domain (which knows about ``NombreFoto`` / sentinel keys / ``animal_id``)
and the storage client (which knows about the two-step S3-compatible
download flow). The service resolves the animal through the animals
data service, owns the fail-closed policy, and returns bytes plus media
type. The route only translates that typed outcome into an HTTP response.

Why this boundary exists:

- The route layer cannot decide what counts as "missing" (sentinel,
  None, storage 404). That is a domain decision; the service owns it.
- The storage client cannot decide what animal_id or NombreFoto to use
  (those are domain terms). That would couple transport to domain.
- Both responsibilities together would duplicate the authorization /
  fail-closed logic. The service is the seam.

Three-path behavior:

- Happy: a real ``NombreFoto`` and a working storage → byte iterator.
- Sad (storage failure): any error from ``download_object_stream``
  EAGERLY or mid-iteration → ``PhotoStreamError`` so the route can
  render the placeholder. Mid-iteration errors are caught inside
  the generator itself, BEFORE the route's ``StreamingResponse``
  starts streaming — the route pre-advances the generator with
  ``next(byte_iter)`` to surface them.
- Edge (missing/sentinel): no storage call at all, raise
  ``PhotoStreamError`` immediately.

The byte iterator returned by the service is consumed by the route via
FastAPI ``StreamingResponse``; the iterator is closed implicitly when
the response finishes. The iterator MUST NOT include any URL/header
metadata — only the object bytes — because the route serialises it
directly to the client.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.modules.animals import service as animals_service

PHOTO_BUCKET = "apap-photos"
SENTINEL_KEY = "__missing__"
PLACEHOLDER_PHOTO_PNG: bytes = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02"
    b"\xfeA\xc0\xc1\x00\x00\x00\x00IEND\xaeB`\x82"
)

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
    """Resolved bytes and media type for the route's HTTP response."""

    content: bytes
    media_type: str


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

    # Iterate lazily; wrap mid-stream errors as PhotoStreamError so the
    # route's outer ``try / next(byte_iter)`` catches them on the FIRST
    # failing iteration. ``StreamingResponse`` never sees the raw
    # exception because the failure surfaces before headers are sent.
    try:
        yield from byte_iter
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


def resolve_animal_photo(
    client: _PhotoClient,
    animal_id: str,
) -> PhotoResolution | None:
    """Resolve the fail-closed photo policy without constructing HTTP responses.

    ``None`` is reserved for a genuinely missing animal so the route can emit
    404. Lookup failures, missing/sentinel keys, storage failures, and empty
    objects all resolve to the placeholder PNG.
    """
    try:
        animal = animals_service.get_animal_by_id(client, animal_id)
    except Exception as exc:  # noqa: BLE001 — established fail-closed contract
        log_safe(
            "animal_foto.sql_lookup_failed",
            reason=type(exc).__name__,
        )
        return PhotoResolution(PLACEHOLDER_PHOTO_PNG, "image/png")

    if animal is None:
        return None
    if is_missing_nombrefoto(animal.NombreFoto):
        return PhotoResolution(PLACEHOLDER_PHOTO_PNG, "image/png")

    try:
        chunks = list(
            stream_animal_photo(client, nombrefoto=animal.NombreFoto)
        )
    except PhotoStreamError:
        return PhotoResolution(PLACEHOLDER_PHOTO_PNG, "image/png")
    if not chunks:
        return PhotoResolution(PLACEHOLDER_PHOTO_PNG, "image/png")
    return PhotoResolution(
        b"".join(chunks),
        content_type_for_key(animal.NombreFoto),
    )


__all__ = [
    "PHOTO_BUCKET",
    "PLACEHOLDER_PHOTO_PNG",
    "SENTINEL_KEY",
    "PhotoResolution",
    "PhotoStreamError",
    "content_type_for_key",
    "is_missing_nombrefoto",
    "resolve_animal_photo",
    "stream_animal_photo",
]
