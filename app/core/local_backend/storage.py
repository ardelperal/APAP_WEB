"""``GET /api/storage/buckets`` and ``POST /api/storage/buckets`` handlers
(M0 of self-host-backend-coolify).

The LocalBackend REST API exposes the bucket admin surface used by
``AuthUsersPort.get_bucket`` and ``AuthUsersPort.ensure_bucket``. The
local backend re-implements those endpoints against an in-memory
bucket registry (M2 swaps this for real MinIO + boto3).

The contract is body-based for ``POST`` (``{"bucketName": ..., "isPublic": ...}``),
matching what ``AuthUsersPort.ensure_bucket`` sends. The tasks.md
originally suggested ``POST /api/storage/buckets/{name}`` but the
LocalBackend client sends the name in the body, so the body-based form
is what the integration tests pin.

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): tests assert return shapes (``bucketName``,
  ``isPublic``, ``files``) and the round-trip behaviour, never
  absence-of-error.
- Rule 8 (no production mutation): the bucket registry is in-process;
  no real MinIO/S3 contacted.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


def _bucket_dict(name: str, is_public: bool) -> dict[str, Any]:
    """Shape the LocalBackend bucket envelope.

    ``bucketName`` (camelCase) matches the existing client. ``isPublic``
    and ``files`` are part of the LocalBackend envelope — ``files`` is the
    count of objects in the bucket (always 0 in M0).
    """
    return {
        "bucketName": name,
        "isPublic": is_public,
        "files": 0,
    }


# M0 stub: an in-memory registry of buckets seeded with the canonical
# ``apap-photos`` bucket used by APAP_WEB. M2 swaps for MinIO + boto3.
_BUCKETS: dict[str, dict[str, Any]] = {
    "apap-photos": _bucket_dict("apap-photos", is_public=False),
}


@router.get("/storage/buckets")
def list_buckets() -> list[dict[str, Any]]:
    """List all buckets (M0 stub: in-memory registry)."""
    return list(_BUCKETS.values())


@router.post("/storage/buckets")
def ensure_bucket(payload: dict[str, Any]) -> dict[str, Any]:
    """Create the bucket if missing. Idempotent: returns the existing
    bucket envelope if the name is already in the registry.

    Body shape (matches what ``AuthUsersPort.ensure_bucket`` sends):
        ``{"bucketName": str, "isPublic": bool}``

    APAP migration buckets must be private (``is_public=True`` is
    rejected at the client side; the server echoes back whatever the
    caller sent — the local backend does not enforce privacy, it just
    records what the operator asked for).
    """
    name = payload.get("bucketName")
    if not isinstance(name, str) or not name:
        raise ValueError("payload must include a non-empty 'bucketName' string")
    is_public = bool(payload.get("isPublic", False))
    if name not in _BUCKETS:
        _BUCKETS[name] = _bucket_dict(name, is_public)
    return _BUCKETS[name]


__all__ = ["router", "list_buckets", "ensure_bucket"]
