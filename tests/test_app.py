"""Tests for the FastAPI application entrypoint.

These tests pin the public HTTP contract of the skeleton: the app
imports cleanly, ``/healthz`` answers 200, and the static directory
is mounted. They run against the real ``app.main`` instance via
FastAPI's ``TestClient`` so any wiring mistake in the entrypoint is
caught here, not in deployment.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_app_is_a_fastapi_instance() -> None:
    """The exported ``app`` object is a FastAPI application."""
    from app.main import app

    assert isinstance(app, FastAPI)


def test_healthz_returns_200_with_status_payload() -> None:
    """``GET /healthz`` returns a JSON status payload with HTTP 200."""
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "APAP_WEB"


def test_static_directory_is_mounted() -> None:
    """The ``/static`` path is served by StaticFiles."""
    from app.main import app

    routes = {route.path for route in app.routes}

    assert "/static" in routes
