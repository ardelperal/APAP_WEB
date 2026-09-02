"""``GET /api/storage/buckets`` and ``POST /api/storage/buckets/{name}`` stubs
(M0 of self-host-backend-coolify).

The full implementation will follow the next TDD step. The stub
returns the shape that ``InsForgeClient.get_bucket`` expects:

  ``[{"bucketName": "apap-photos", "isPublic": false, "files": 0}, ...]``

(bucketName camelCase matches the existing client; isPublic and files
match the InsForge envelope shape.)
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


_BUCKETS = [
    {"bucketName": "apap-photos", "isPublic": False, "files": 0},
]


@router.get("/storage/buckets")
def list_buckets() -> list[dict]:
    """List all buckets (M0 stub: one fixed bucket)."""
    return list(_BUCKETS)


@router.post("/storage/buckets/{bucket_name}")
async def ensure_bucket(bucket_name: str, is_public: bool = False) -> dict:
    """Create the bucket if missing. M0 stub always returns success."""
    return {
        "bucketName": bucket_name,
        "isPublic": is_public,
        "files": 0,
    }
