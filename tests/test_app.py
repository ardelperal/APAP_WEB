"""Tests for the FastAPI application entrypoint.

The ``client`` fixture (see ``tests/conftest.py``) provides an
``httpx.AsyncClient`` wired to a fresh app via ``httpx.ASGITransport``,
the current recommended pattern for ASGI testing. No use of the
deprecated ``starlette.testclient.TestClient``.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.main import app as module_app


def test_app_is_a_fastapi_instance() -> None:
    """The exported ``app`` object is a FastAPI application."""
    assert isinstance(module_app, FastAPI)


async def test_healthz_returns_200_with_status_payload(client: httpx.AsyncClient) -> None:
    """``GET /healthz`` returns a JSON status payload with HTTP 200."""
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "APAP_WEB"


async def test_static_directory_is_mounted(client: httpx.AsyncClient) -> None:
    """The ``/static`` path is served by StaticFiles."""
    from app.main import app

    # ``app.routes`` may include ``_IncludedRouter`` objects (when sub-routers
    # are mounted) which don't expose ``.path``; filter them out.
    routes = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/static" in routes
