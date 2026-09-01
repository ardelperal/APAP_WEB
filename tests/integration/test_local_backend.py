"""Tests for the M0 local backend (issue #641, self-host-backend-coolify).

The M0 milestone replaces InsForge (the managed BaaS) with a FastAPI
backend served by the same process, over Postgres. The tests below
pin the contract that ``InsForgeClient`` consumes regardless of whether
the backend is InsForge remote or the local one.

Test layering:
- Unit tests for the URL-switching (InsForgeClient constructor).
- Integration tests for the local backend's /api/database/advance/rawsql
  endpoint (proves the JSON shape that the client expects).
- Integration tests for /api/storage/buckets (proves the bucket shape).

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state.
- Rule 4 (no humo): assertions on real behaviour (JSON shapes, SQL
  round-trips), never absence-of-error.
- Rule 8 (no production mutation): the integration backend runs
  in-process on a random port; no real InsForge is contacted.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.core.insforge import InsForgeClient


# --- URL switching (unit-level) -------------------------------------------


def test_insforge_client_defaults_to_insforge_url() -> None:
    """When ``APAP_LOCAL_BACKEND`` is unset, the client targets InsForge.

    The default URL is whatever the operator configured in
    ``APAP_INSFORGE_URL`` (defaulting to the published placeholder).
    """
    client = InsForgeClient(
        base_url="https://insforge.example.com",
        service_key="dummy",
    )
    assert client._client.base_url == "https://insforge.example.com"


def test_insforge_client_uses_local_default_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``APAP_LOCAL_BACKEND=true`` is set and ``APAP_INSFORGE_URL``
    is empty, the client targets ``http://localhost:8000/api``.

    The local backend is mounted at the same prefix (``/api``) as the
    InsForge API so the rest of the application code does not need
    to know which backend is in use.
    """
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    client = InsForgeClient(
        base_url="",
        service_key="dummy",
    )
    assert client._base_url == "http://localhost:8000/api"


def test_insforge_client_local_url_overrides_local_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APAP_INSFORGE_URL`` always wins over the local default.

    The local flag only applies when the operator left the URL empty.
    An explicit URL is honoured as-is. This keeps production
    deployments that point at a custom InsForge instance working.
    """
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", "https://custom-insforge.example.com")
    client = InsForgeClient(
        base_url=os.environ["APAP_INSFORGE_URL"],
        service_key="dummy",
    )
    assert client._client.base_url == "https://custom-insforge.example.com"


# --- Local backend API (integration) ---------------------------------------


def _free_port() -> int:
    """Return a free TCP port for the local backend to bind."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_local_backend(db_url: str, s3_endpoint: str, port: int):
    """Start the local backend in a thread, return the uvicorn server."""
    os.environ["APAP_LOCAL_DB_URL"] = db_url
    os.environ["APAP_S3_ENDPOINT_URL"] = s3_endpoint
    os.environ["APAP_S3_ACCESS_KEY"] = "testkey"
    os.environ["APAP_S3_SECRET_KEY"] = "testsecret"
    os.environ["APAP_S3_BUCKET"] = "test-bucket"

    from app.core.local_backend.api import app as local_app

    config = uvicorn.Config(
        local_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for the server to come up (max 5s).
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("local backend did not start")
    return server, thread


@pytest.fixture
def local_backend(self_host_schema):
    """Start the local backend on a random port, talking to the same
    Postgres that the rest of the integration tests use. Provide a
    ``base_url`` for the client to point at.
    """
    port = _free_port()
    server, thread = _start_local_backend(
        db_url=os.environ["APAP_TEST_POSTGRES_DSN"],
        s3_endpoint="http://127.0.0.1:9000",
        port=port,
    )
    base_url = f"http://127.0.0.1:{port}/api"
    yield base_url
    server.should_exit = True
    thread.join(timeout=5)


def test_local_backend_healthz(local_backend: str) -> None:
    """/healthz returns 200 with a JSON body."""
    with httpx.Client(base_url=local_backend, timeout=5) as c:
        r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "up"
    assert body["storage"] == "up"


def test_local_backend_rawsql_select_roundtrip(
    local_backend: str, self_host_schema
) -> None:
    """``POST /api/database/advance/rawsql`` with a SELECT returns rows.

    Pins the JSON shape that ``InsForgeClient.execute_sql`` consumes:
    ``{"rows": [...], "rowCount": int}``. The integration conftest
    provisions the domain tables; the test inserts a row and then
    queries it through the new backend to prove the round-trip works
    against the real Postgres engine.
    """
    self_host_schema.execute_sql(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES (%s, %s, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-FIX-001", "Test"],
    )
    with httpx.Client(base_url=local_backend, timeout=5) as c:
        r = c.post(
            "/api/database/advance/rawsql",
            json={
                "query": "SELECT nchip, nombreanimal FROM animales WHERE nchip = $1",
                "params": ["CHIP-FIX-001"],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["rowCount"] == 1
    assert body["rows"][0]["nchip"] == "CHIP-FIX-001"
    assert body["rows"][0]["nombreanimal"] == "Test"


def test_local_backend_rawsql_insert_returns_empty_rows(
    local_backend: str, self_host_schema
) -> None:
    """INSERT returns ``{"rows": [], "rowCount": 0}`` (matches InsForge)."""
    with httpx.Client(base_url=local_backend, timeout=5) as c:
        r = c.post(
            "/api/database/advance/rawsql",
            json={
                "query": (
                    "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
                    "VALUES (%s, %s, 'CANINA', 'H', '2020-01-01')"
                ),
                "params": ["CHIP-FIX-002", "Test2"],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == []
    assert body["rowCount"] == 0

    # The row is actually inserted.
    rows = self_host_schema.execute_sql(
        "SELECT nchip FROM animales WHERE nchip = %s", ["CHIP-FIX-002"]
    )
    assert rows[0]["nchip"] == "CHIP-FIX-002"


def test_local_backend_rawsql_error_returns_4xx(
    local_backend: str,
) -> None:
    """A query that violates a constraint returns 4xx, not 500.

    Mirrors the InsForge contract (constraint violations are 4xx,
    runtime errors are 5xx).
    """
    with httpx.Client(base_url=local_backend, timeout=5) as c:
        r = c.post(
            "/api/database/advance/rawsql",
            json={
                "query": "SELECT * FROM animales WHERE nchip = $1",
                "params": [],  # missing required param
            },
        )
    assert 400 <= r.status_code < 500


def test_local_backend_storage_get_bucket(
    local_backend: str,
) -> None:
    """``GET /api/storage/buckets/{name}`` returns the bucket shape
    that ``InsForgeClient.get_bucket`` expects (or 404 if missing).
    """
    # Bucket is auto-created at startup; this should return 200.
    with httpx.Client(base_url=local_backend, timeout=5) as c:
        r = c.get("/api/storage/buckets/test-bucket")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "test-bucket"
    assert body["isPublic"] is False
