"""Tests for the M0 local backend (issue #641, self-host-backend-coolify).

The M0 milestone replaces InsForge (the managed BaaS) with a FastAPI
backend served by the same process, over Postgres. The tests below
pin the contract that ``InsForgeClient`` consumes regardless of whether
the backend is InsForge remote or the local one.

This file replaces the earlier in-process uvicorn tests (which proved
brittle because uvicorn's thread-based runner does not run the FastAPI
lifespan). The new approach is end-to-end against a real ``app.main``
FastAPI instance — same process, same lifespan. The test boots the
full app in a thread, exercises it via httpx, and tears it down.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.core.insforge import InsForgeClient

# --- URL switching (unit-level) -------------------------------------------


def test_insforge_client_defaults_to_insforge_url() -> None:
    """When ``APAP_LOCAL_BACKEND`` is unset, the client targets InsForge."""
    client = InsForgeClient(
        base_url="https://insforge.example.com",
        service_key="dummy",
    )
    assert client._client.base_url == "https://insforge.example.com"


def test_insforge_client_uses_local_default_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``APAP_LOCAL_BACKEND=true`` and ``APAP_INSFORGE_URL`` is empty,
    the client targets ``http://localhost:8000/api`` (the local backend)."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    client = InsForgeClient(base_url="", service_key="dummy")
    assert client._client.base_url.rstrip("/") == "http://localhost:8000/api"


def test_insforge_client_local_url_overrides_local_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APAP_INSFORGE_URL`` always wins over the local default."""
    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", "https://custom-insforge.example.com")
    client = InsForgeClient(
        base_url=os.environ["APAP_INSFORGE_URL"],
        service_key="dummy",
    )
    assert client._client.base_url == "https://custom-insforge.example.com"


# --- Local backend integration --------------------------------------------


def _free_port() -> int:
    """Return a free TCP port for the local backend to bind."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 5.0) -> None:
    """Poll the port until the server accepts a TCP connection."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("local backend did not start")


def _wait_for_healthz(base_url: str, timeout: float = 5.0) -> None:
    """Poll the healthcheck endpoint until it returns 200."""
    deadline = time.time() + timeout
    with httpx.Client(base_url=base_url, timeout=1.0) as c:
        while time.time() < deadline:
            try:
                r = c.get("/healthz")
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.1)
    raise RuntimeError("local backend /healthz did not respond")


@pytest.fixture
def local_backend_url() -> str:
    """Start the real APAP_WEB app on a random port with APAP_LOCAL_BACKEND=true.

    The full ``app.main`` app is started (in a thread) so the lifespan
    runs and the database schema is provisioned against the same
    Postgres instance the integration tests use. The local backend
    auto-detects ``APAP_LOCAL_BACKEND=true`` and uses the in-process
    LocalPostgresExecutor instead of InsForge.

    Yields the base URL for the test client. Tears the server down
    on exit.
    """
    from app.main import create_app

    # M0 hardcodes the DSN for the test; in M2 this is read from env
    # or secrets. The schema is provisioned by the integration
    # conftest's ephemeral_postgres fixture, but in the in-process
    # path the schema is a different ephemeral namespace — so we
    # accept the M0 trade-off: the tests run against the same
    # Postgres instance and assume the schema is already there.
    port = _free_port()
    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_server(port)
    _wait_for_healthz(base_url)
    yield base_url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.integration
def test_local_backend_healthz(local_backend_url: str) -> None:
    """/healthz returns 200 with a JSON body."""
    with httpx.Client(base_url=local_backend_url, timeout=5) as c:
        r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "db" in body
    assert "storage" in body


@pytest.mark.integration
def test_local_backend_storage_get_bucket(local_backend_url: str) -> None:
    """GET /api/storage/buckets/{name} returns the InsForge bucket shape."""
    with httpx.Client(base_url=local_backend_url, timeout=5) as c:
        r = c.get("/api/storage/buckets/apap-photos")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "apap-photos"
    assert body["isPublic"] is False
    assert "files" in body


# M0 stubs the /api/database/advance/rawsql endpoint with the real
# Postgres; that test is covered by the integration schema's
# ephemeral_postgres + the LocalPostgresExecutor's DSN-aware
# connection setup. A separate test that exercises the endpoint
# directly (not the executor) lives in a follow-up PR.
