"""Tests for the generic unhandled-error handler in ``app/main.py``.

§32.P4 (issues #277, #278): a route that catches only its domain error
(``ValueError``) and lets transport errors propagate uncaught becomes
a 500. The generic ``@app.exception_handler(Exception)`` registered in
``app/main.py`` turns every unhandled exception into a non-leaking 502
with ``log_safe`` observability.

This test replaces the slice-level tests that used to live at
``tests/test_backend_error_handler.py`` and
``tests/test_slice_backend_error_handler.py`` (deleted in #662 with
the rest of the LocalBackend error-handler slice).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app_with_boom() -> FastAPI:
    """Build a minimal FastAPI app whose ``/boom`` route raises ``RuntimeError``."""
    app = FastAPI()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("synthetic transport failure")

    # Re-register the same generic handler the production app uses.
    from fastapi import Request
    from fastapi.responses import JSONResponse

    from app.core.logging import log_safe

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        log_safe(
            "server.unhandled_error",
            path=request.url.path,
            method=request.method,
            exc_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Internal server error"},
        )

    return app


def test_unhandled_exception_returns_502_with_non_leaking_body() -> None:
    """An unhandled exception surfaces as a 502 with no stack trace / payload leak."""
    client = TestClient(_build_app_with_boom(), raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 502
    body = response.json()
    assert body == {"detail": "Internal server error"}
    # The synthetic message and the RuntimeError type name must NOT leak.
    assert "synthetic transport failure" not in str(body)
    assert "RuntimeError" not in str(body)


def test_http_exception_not_handled_by_generic_handler() -> None:
    """FastAPI's built-in HTTPException handler still wins for 4xx responses."""
    from fastapi import HTTPException

    app = FastAPI()

    @app.get("/forbidden")
    def forbidden() -> None:
        raise HTTPException(status_code=403, detail="nope")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/forbidden")

    assert response.status_code == 403
    assert response.json() == {"detail": "nope"}


def test_validation_error_returns_422_not_502() -> None:
    """Request validation errors remain 422 (FastAPI's built-in handler)."""
    from pydantic import BaseModel

    app = FastAPI()

    class Payload(BaseModel):
        n: int

    @app.post("/echo")
    def echo(payload: Payload) -> dict[str, int]:
        return {"n": payload.n}

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/echo", json={"n": "not-an-int"})

    assert response.status_code == 422
