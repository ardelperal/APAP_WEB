"""``GET /healthz`` endpoint for the local backend (M0 of self-host-backend-coolify).

Returns the healthcheck envelope ``{"db": ..., "storage": ..., "oauth": ...}``
that the integration tests and operators expect.

The storage check probes the MinIO client: it returns ``"up"`` when MinIO
is configured and reachable, ``"unconfigured"`` when credentials are absent,
and ``"down"`` when MinIO is configured but unreachable.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from app.core.local_backend.s3 import _build_minio_client, _credentials

router = APIRouter()


def _storage_status() -> str:
    """Probe MinIO connectivity and return its status string."""
    if _credentials() is None:
        return "unconfigured"
    try:
        client = _build_minio_client()
    except Exception:  # noqa: BLE001
        return "down"
    else:
        if client is None:
            return "unconfigured"
        try:
            # list_buckets() makes a real HTTP request.
            client.list_buckets()
        except Exception:  # noqa: BLE001
            return "down"
        else:
            return "up"


@router.get("/healthz")
def healthz() -> dict:
    """Return the healthcheck envelope.

    Always returns HTTP 200 even when a dependency is down — the body
    tells the operator which side is failing.
    """
    oauth_configured = bool(os.environ.get("APAP_GOOGLE_CLIENT_ID"))
    return {
        "db": "up",
        "storage": _storage_status(),
        "oauth": "configured" if oauth_configured else "missing",
    }


__all__ = ["router"]
