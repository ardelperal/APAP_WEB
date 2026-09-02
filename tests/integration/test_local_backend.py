"""Tests for the M0 local backend (issue #641, self-host-backend-coolify).

The M0 milestone replaces InsForge (the managed BaaS) with a FastAPI
backend served by the same process, over Postgres. The tests below
pin the contract that ``InsForgeClient`` consumes regardless of whether
the backend is InsForge remote or the local one.

This file replaces the earlier in-process uvicorn tests (which proved
brittle because uvicorn's thread-based runner does not run the FastAPI
lifespan reliably — a previous in-session attempt at uvicorn threads
failed with ``SystemExit: 3``). The new approach is end-to-end
against a real ``app.main`` FastAPI instance via
``httpx.AsyncClient(ASGITransport=app)`` which executes the lifespan
correctly and matches the project's existing integration test style.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state.
- Rule 4 (no humo): assertions on real behaviour (JSON shapes, status
  codes), never absence-of-error.
- Rule 8 (no production mutation): the local backend runs in-process
  via ASGITransport; no real InsForge is contacted.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.core.local_backend.app import create_app


# --- URL switching (unit-level) -------------------------------------------


def test_insforge_client_defaults_to_insforge_url() -> None:
    """When ``APAP_LOCAL_BACKEND`` is unset, the client targets InsForge."""
    from app.core.insforge import InsForgeClient

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
    from app.core.insforge import InsForgeClient

    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.delenv("APAP_INSFORGE_URL", raising=False)
    client = InsForgeClient(base_url="", service_key="dummy")
    assert client._client.base_url.rstrip("/") == "http://localhost:8000/api"


def test_insforge_client_local_url_overrides_local_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APAP_INSFORGE_URL`` always wins over the local default."""
    from app.core.insforge import InsForgeClient

    monkeypatch.setenv("APAP_LOCAL_BACKEND", "true")
    monkeypatch.setenv("APAP_INSFORGE_URL", "https://custom-insforge.example.com")
    client = InsForgeClient(
        base_url=os.environ["APAP_INSFORGE_URL"],
        service_key="dummy",
    )
    assert client._client.base_url == "https://custom-insforge.example.com"


# --- Local backend integration --------------------------------------------


@pytest.fixture
def local_backend_client(self_host_schema) -> httpx.AsyncClient:
    """Stand up the local backend in-process and yield an httpx client.

    The factory (``create_app``) is preferred over a module-level
    ``app`` because module-level FastAPI instances skip the lifespan
    in some test setups. The lifespan reads ``APAP_LOCAL_DB_URL`` from
    the env (set by the test's DSN) and ``APAP_LOCAL_DB_SCHEMA`` (the
    ephemeral schema) so the executor queries the right namespace.
    """
    os.environ["APAP_LOCAL_DB_URL"] = os.environ["APAP_TEST_POSTGRES_DSN"]
    os.environ["APAP_LOCAL_DB_SCHEMA"] = self_host_schema.schema

    app = create_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.asyncio
async def test_healthz_returns_200_and_db_status(
    local_backend_client: httpx.AsyncClient,
) -> None:
    """``GET /healthz`` returns 200 with the expected body shape."""
    async with local_backend_client as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "db" in body
    assert body["db"] in ("up", "down")
    assert "storage" in body
    assert body["storage"] in ("up", "down")
    assert "oauth" in body
    assert body["oauth"] in ("configured", "missing")
