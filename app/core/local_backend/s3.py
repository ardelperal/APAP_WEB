"""MinIO / S3-compatible object storage client for APAP_WEB (issue #641).

This module exposes a MinIO client singleton built from environment variables.
The lifespan of ``app/main`` and ``app/core/local_backend/app`` both wire
``app.state.minio_client`` from this module.

The client implements ``PhotoStorageClient`` (download only) for the photo
asset pipeline and the ``MinioClient`` protocol for the bucket-admin
surface used by the local-backend API.

Environment variables
--------------------
``APAP_S3_ENDPOINT``
    MinIO server address, e.g. ``minio:9000``.  Defaults to ``localhost:9000``.
``APAP_S3_ACCESS_KEY``
    MinIO access key.  Required when ``APAP_S3_SECRET_KEY`` is set.
``APAP_S3_SECRET_KEY``
    MinIO secret key.  Required when ``APAP_S3_ACCESS_KEY`` is set.
``APAP_S3_BUCKET``
    Default bucket name for photo assets.  Defaults to ``apap-photos``.
``APAP_S3_SECURE``
    Set to ``0`` or ``false`` to disable TLS.  Default: ``true``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from minio import Minio


def _endpoint() -> str:
    return os.environ.get("APAP_S3_ENDPOINT", "minio:9000")


def _credentials() -> tuple[str, str] | None:
    key = os.environ.get("APAP_S3_ACCESS_KEY", "").strip()
    secret = os.environ.get("APAP_S3_SECRET_KEY", "").strip()
    if key and secret:
        return key, secret
    return None


def _secure() -> bool:
    val = os.environ.get("APAP_S3_SECURE", "true").strip().lower()
    return val not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# MinioClient protocol — consumed by the local-backend API
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    from minio import Minio


class MinioClient:
    """MinIO / S3-compatible client for the storage API.

    Constructed by :func:`build_minio_client`.  Exposes the methods
    consumed by :mod:`app.core.local_backend.storage`.
    """

    def __init__(self, client: Minio) -> None:
        self._client = client

    def list_buckets(self) -> list[dict[str, Any]]:
        """Return the real bucket list from MinIO.

        Each dict has ``name``, ``isPublic`` (always ``False``), and
        ``files`` (count of objects, always ``0`` in this implementation).
        """
        buckets = self._client.list_buckets()
        return [
            {
                "name": b.name,
                "isPublic": False,
                "files": 0,
            }
            for b in buckets
        ]

    def ensure_bucket(self, bucket_name: str) -> dict[str, Any]:
        """Create ``bucket_name`` if it does not exist.

        Returns the bucket dict.  Idempotent — calling twice with the same
        name is safe.
        """
        if not self._client.bucket_exists(bucket_name):
            self._client.make_bucket(bucket_name)
        return {"name": bucket_name, "isPublic": False, "files": 0}


# ---------------------------------------------------------------------------
# PhotoStorageClient protocol — consumed by the photo asset pipeline
# ---------------------------------------------------------------------------

#: Sentinel returned when MinIO is not configured or unreachable.
_UNCONFIGURED: Any = object()


def _unconfigured_client() -> Minio | None:
    creds = _credentials()
    if creds is None:
        return None
    try:
        from minio import Minio  # lazy-import: only needed when S3 credentials exist

        return Minio(
            _endpoint(),
            access_key=creds[0],
            secret_key=creds[1],
            secure=_secure(),
        )
    except Exception:  # noqa: BLE001
        return None


def _build_minio_client() -> Minio | None:
    """Build a MinIO client from environment variables, or return None.

    Returns ``None`` when ``APAP_S3_ACCESS_KEY`` / ``APAP_S3_SECRET_KEY``
    are not set.  Callers must handle the ``None`` case gracefully.
    """
    return _unconfigured_client()


class PhotoStorageClient:
    """MinIO-backed photo storage.

    Satisfies the ``PhotoStorageClient`` protocol used by
    :func:`app.modules.animals.adapters.local_backend
    .animals_local_backend_photo.resolve_animal_photo`.

    When MinIO is not configured the client returns an empty iterator so
    the caller falls back to the placeholder photo.
    """

    def __init__(self) -> None:
        self._client: Minio | None = _build_minio_client()
        self._bucket = os.environ.get("APAP_S3_BUCKET", "apap-photos")

    def download_object_stream(
        self, bucket: str, key: str
    ) -> Iterator[bytes]:
        """Stream the object ``key`` from ``bucket``.

        Raises ``StopIteration`` when the object does not exist.
        Raises any MinIO error when the connection fails.
        """
        if self._client is None:
            raise StopIteration
        response = self._client.get_object(bucket, key)
        try:
            while chunk := response.read(8192):
                yield chunk
        finally:
            response.close()
            response.release_conn()


# ---------------------------------------------------------------------------
# Module-level singleton (lazily constructed)
# ---------------------------------------------------------------------------

_client: MinioClient | None = None


def get_minio_client() -> MinioClient | None:
    """Return the shared ``MinioClient`` instance, or ``None`` when MinIO is not configured."""
    global _client  # noqa: PLW0603
    if _client is None:
        mc = _build_minio_client()
        if mc is not None:
            _client = MinioClient(mc)
    return _client


def reset_minio_client() -> None:
    """Reset the shared client — for use in tests."""
    global _client  # noqa: PLW0603
    _client = None


__all__ = [
    "PhotoStorageClient",
    "MinioClient",
    "get_minio_client",
    "reset_minio_client",
    "_build_minio_client",
]
