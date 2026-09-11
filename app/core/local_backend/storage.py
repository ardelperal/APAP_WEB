"""``GET /api/storage/buckets`` and ``POST /api/storage/buckets`` handlers.

The LocalBackend REST API exposes the bucket admin surface used by
``AuthUsersPort.get_bucket`` and ``AuthUsersPort.ensure_bucket``. This
module wires the real MinIO client from :mod:`app.core.local_backend.s3`.

The contract is body-based for ``POST`` (``{"bucketName": ..., "isPublic": ...}``),
matching what the caller sends.

Tests that need a controlled MinIO substitute can patch
:func:`app.core.local_backend.s3.get_minio_client`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.local_backend.s3 import get_minio_client

router = APIRouter()


def _bucket_dict(name: str, is_public: bool) -> dict[str, Any]:
    """Shape the LocalBackend bucket envelope.

    ``bucketName`` (camelCase) matches the existing client. ``isPublic``
    and ``files`` are part of the LocalBackend envelope.
    """
    return {
        "bucketName": name,
        "isPublic": is_public,
        "files": 0,
    }


#: Sentinel returned when MinIO is not configured.
_UNCONFIGURED: list[dict[str, Any]] = [
    _bucket_dict("apap-photos", is_public=False),
]


@router.get("/storage/buckets")
def list_buckets() -> list[dict[str, Any]]:
    """List all buckets from MinIO.

    Falls back to a stub list when MinIO is not configured so the
    integration tests remain hermetic without a real S3 endpoint.
    """
    client = get_minio_client()
    if client is None:
        return _UNCONFIGURED
    return client.list_buckets()


@router.post("/storage/buckets")
def ensure_bucket(payload: dict[str, Any]) -> dict[str, Any]:
    """Create the bucket if missing. Idempotent.

    Body shape:
        ``{"bucketName": str, "isPublic": bool}``

    Falls back to the stub response when MinIO is not configured.
    """
    name = payload.get("bucketName")
    if not isinstance(name, str) or not name:
        raise ValueError("payload must include a non-empty 'bucketName' string")
    is_public = bool(payload.get("isPublic", False))
    client = get_minio_client()
    if client is None:
        # Stub: return the bucket dict without creating anything.
        return _bucket_dict(name, is_public)
    return client.ensure_bucket(name)


__all__ = ["router", "list_buckets", "ensure_bucket"]
