"""Photo display service for animal photos in the private ``apap-photos`` bucket.

The service is the single-responsibility bridge between the animals
domain (which knows about ``NombreFoto`` / sentinel keys / ``animal_id``)
and the storage client (which knows about the two-step S3-compatible
download flow). The service has NO SQL knowledge — it receives the
storage client and the animal row from the caller — and the route has
NO storage knowledge — it asks the service for a byte iterator or a
typed "missing" outcome and translates that into an HTTP response.

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
  → ``PhotoStreamError`` so the route can render the placeholder.
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
from typing import Any, Protocol  # noqa: F401 — Protocol used in _StorageLike

PHOTO_BUCKET = "apap-photos"
SENTINEL_KEY = "__missing__"


class PhotoStreamError(RuntimeError):
    """Raised when the photo stream cannot be produced.

    Covers the three failure modes the route must translate to a
    placeholder PNG: sentinel/missing key, storage transport failure,
    and InsForge-shaped errors raised by the storage client. The
    service intentionally uses one error type so the route can
    surface a single, stable fail-closed contract.
    """


class _StorageLike(Protocol):
    """Minimal storage surface the service depends on.

    Mirrors ``InsForgeClient.download_object_stream`` so tests can
    pass a fake without subclassing ``InsForgeClient``.
    """

    def download_object_stream(
        self, bucket: str, key: str
    ) -> Iterator[bytes]: ...


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
      BEFORE any storage call (no I/O cost).
    - Storage transport raises (``httpx.TimeoutException``,
      ``InsForgeError``, ``RuntimeError``, ...) → raise
      ``PhotoStreamError`` carrying the original exception as
      ``__cause__`` so the operator can still trace it.
    - Storage returns an iterator → yield the bytes verbatim.

    The iterator contract: the caller drains it via
    ``StreamingResponse``. The service does NOT close the underlying
    HTTP stream — the storage client owns the connection lifecycle.
    """
    if is_missing_nombrefoto(nombrefoto):
        raise PhotoStreamError(
            "animal has no NombreFoto (missing/sentinel); serving placeholder"
        )

    try:
        return storage_client.download_object_stream(PHOTO_BUCKET, nombrefoto)
    except PhotoStreamError:
        # Re-raise without wrapping so the route's exception handling
        # sees the typed error directly.
        raise
    except Exception as exc:  # noqa: BLE001 — the route needs a single typed surface
        raise PhotoStreamError(
            f"photo stream failed for {nombrefoto!r}"
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
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


__all__ = [
    "PHOTO_BUCKET",
    "SENTINEL_KEY",
    "PhotoStreamError",
    "content_type_for_key",
    "is_missing_nombrefoto",
    "stream_animal_photo",
]
