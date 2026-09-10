"""Tests for the M0 local backend (issue #641, self-host-backend-coolify).

The M0 milestone replaces InsForge (the managed BaaS) with a FastAPI
backend served by the same process, over Postgres. The tests below
exercise the local backend stack that the docker-compose.yml spins up.

The ``local_backend_url`` fixture starts ``app.main:create_app()`` in
a thread so the lifespan runs (schema bootstrap, MinIO wiring).

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


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


def _wait_for_healthz(port: int, timeout: float = 5.0) -> None:
    """Poll the health endpoint until it returns 200."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=1.0) as c:
                r = c.get(f"http://127.0.0.1:{port}/healthz")
                if r.status_code == 200:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("local backend /healthz did not respond")


@pytest.fixture
def local_backend_url() -> pytest.Iterator[str]:
    """Start ``app.main:create_app()`` in a thread and yield its base URL.

    The app's lifespan provisions the schema against the integration
    Postgres.  The MinIO health probe in ``/healthz`` will reflect
    whether ``APAP_S3_ACCESS_KEY`` / ``APAP_S3_SECRET_KEY`` are set.
    """
    from app.main import create_app

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
    _wait_for_server(port)
    _wait_for_healthz(port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_healthz_returns_200_with_json_body(local_backend_url: str) -> None:
    """``GET /healthz`` returns 200 with ``status``, ``app``, ``revision``."""
    with httpx.Client(base_url=local_backend_url, timeout=5) as c:
        r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "app" in body
    assert "revision" in body
