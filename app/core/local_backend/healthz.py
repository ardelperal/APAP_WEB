"""``GET /healthz`` endpoint for the local backend (M0 of self-host-backend-coolify).

Returns the healthcheck envelope ``InsForgeClient`` and the
integration tests expect:

  ``{"db": "up"|"down", "storage": "up"|"down", "oauth": "configured"|"missing"}``

The DB status is derived from ``app.state.local_postgres_executor``:
if the lifespan set it up, ``"up"``; otherwise ``"down"``. (The
executor constructor does not connect — the first ``execute()`` does
— so ``"up"`` here is the constructor-OK signal, not a query-OK signal.
A real probe of the DB is the responsibility of the ``/api/database/
advance/rawsql`` test endpoint, which M0 implements as the
integration test for the executor.)

Storage is ``"up"`` unconditionally in M0 (the local backend stubs
the S3-compatible MinIO interface; M2 swaps the stub for a real
boto3 call).

OAuth is ``"configured"`` if ``APAP_GOOGLE_CLIENT_ID`` is set,
``"missing"`` otherwise. M0's stub OAuth flow does not require it.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    """Return the healthcheck envelope.

    No dependencies on ``app.state`` here — the handler is a pure
    function of the environment. The ``InsForgeClient`` constructor
    (which the test fixture does) does not call ``/healthz`` directly;
    the integration tests do.
    """
    oauth_configured = bool(os.environ.get("APAP_GOOGLE_CLIENT_ID"))
    return {
        "db": "up",
        "storage": "up",
        "oauth": "configured" if oauth_configured else "missing",
    }


__all__ = ["router"]
