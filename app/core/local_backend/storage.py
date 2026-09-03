"""In-memory bucket registry for the local backend (M0 stub)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

storage_router = APIRouter()

_BUCKET_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_BUCKET_NAME_RE = re.compile(_BUCKET_NAME_PATTERN)


_BUCKETS: dict[str, dict[str, object]] = {
    "apap-photos": {"bucketName": "apap-photos", "isPublic": False, "files": 0},
}


@storage_router.get("/storage/buckets")
async def list_buckets() -> list[dict[str, object]]:
    """Return every entry in the in-memory bucket registry."""
    return list(_BUCKETS.values())


@storage_router.post("/storage/buckets/{bucket_name}")
async def ensure_bucket(bucket_name: str) -> dict[str, object]:
    """Create the bucket on demand (idempotent) and return its descriptor.

    Validates ``bucket_name`` against ``^[A-Za-z0-9_-]{1,64}$`` and returns
    HTTP 400 on mismatch — FastAPI's built-in ``Path(pattern=...)`` raises
    422, so the validation is done explicitly here to honour the R3
    contract that bad names are user errors, not schema errors.
    """
    if not _BUCKET_NAME_RE.match(bucket_name):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_bucket_name",
                "detail": f"bucket name {bucket_name!r} must match {_BUCKET_NAME_PATTERN}",
            },
        )
    entry = _BUCKETS.get(bucket_name)
    if entry is None:
        entry = {"bucketName": bucket_name, "isPublic": False, "files": 0}
        _BUCKETS[bucket_name] = entry
    return entry


__all__ = ["storage_router", "list_buckets", "ensure_bucket"]
