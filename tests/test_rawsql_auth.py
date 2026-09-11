"""Security tests for the LocalBackend raw-SQL endpoint (issue #680).

The LocalBackend process owns the token validation because it is the only
application that mounts the privileged compatibility router.  Handler tests
exercise the in-process HTTP contract and prove that rejected requests never
reach the SQL executor.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.core.config import Settings, StartupConfigError, _validate_secrets, get_settings
from app.core.local_backend.app import create_app
from app.core.local_backend.rawsql import _require_rawsql_token, router

TOKEN = "a" * 40
GENERIC_AUTH_ERROR = {"detail": "invalid credentials"}


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Keep environment-driven settings isolated between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _ExecutorSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any] | None]] = []

    def execute_sql(
        self, query: str, params: list[Any] | tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        normalized = list(params) if params is not None else None
        self.calls.append((query, normalized))
        return [{"value": 1}]


def _handler_app(expected_token: str = TOKEN) -> tuple[FastAPI, _ExecutorSpy]:
    app = FastAPI()
    executor = _ExecutorSpy()
    app.state.rawsql_auth_token = expected_token
    app.state.local_postgres_executor = executor
    app.include_router(router, prefix="/api")
    return app, executor


@pytest.mark.parametrize(
    "authorization,expected",
    [
        (None, TOKEN),
        ("", TOKEN),
        ("Basic abc", TOKEN),
        ("bearer " + TOKEN, TOKEN),
        ("Bearer wrong", TOKEN),
        ("Bearer " + TOKEN + " ", TOKEN),
        ("Bearer anything", ""),
    ],
)
def test_rawsql_token_gate_is_default_deny_and_generic(
    authorization: str | None, expected: str
) -> None:
    """Every invalid presentation has one non-diagnostic 401 response."""
    with pytest.raises(HTTPException) as exc_info:
        _require_rawsql_token(authorization, expected)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid credentials"
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


def test_rawsql_token_gate_accepts_exact_token() -> None:
    """The exact bearer token passes the constant-time comparison."""
    _require_rawsql_token("Bearer " + TOKEN, TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Bearer wrong"])
async def test_rawsql_handler_rejects_before_executor(
    authorization: str | None,
) -> None:
    """Route integration: denied requests do not execute attacker SQL."""
    app, executor = _handler_app()
    headers = {"Authorization": authorization} if authorization else {}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/database/advance/rawsql",
            headers=headers,
            json={"query": "DROP TABLE usuarios_autorizados", "params": []},
        )

    assert response.status_code == 401
    assert response.json() == GENERIC_AUTH_ERROR
    assert response.headers["www-authenticate"] == "Bearer"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_rawsql_handler_executes_with_exact_token() -> None:
    """Route integration: valid credentials preserve the response contract."""
    app, executor = _handler_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/database/advance/rawsql",
            headers={"Authorization": "Bearer " + TOKEN},
            json={"query": "SELECT $1 AS value", "params": [1]},
        )

    assert response.status_code == 200
    assert response.json() == {"rows": [{"value": 1}], "rowCount": 1}
    assert executor.calls == [("SELECT $1 AS value", [1])]


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "tiny-secret"])
async def test_local_backend_lifespan_rejects_missing_or_weak_token(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    """Application startup fails closed when its mounted router is unusable."""
    monkeypatch.setenv("APAP_LOCAL_DB_URL", "postgresql://unused")
    if token is None:
        monkeypatch.delenv("APAP_RAWSQL_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("APAP_RAWSQL_AUTH_TOKEN", token)
    get_settings.cache_clear()
    app = create_app()

    with pytest.raises(StartupConfigError) as exc_info:
        async with app.router.lifespan_context(app):
            pass

    assert exc_info.value.env_var == "APAP_RAWSQL_AUTH_TOKEN"
    assert token is None or token not in str(exc_info.value)


@pytest.mark.asyncio
async def test_local_backend_lifespan_stores_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strong token is wired to app state for request-time validation."""
    monkeypatch.setenv("APAP_LOCAL_DB_URL", "postgresql://unused")
    monkeypatch.setenv("APAP_RAWSQL_AUTH_TOKEN", TOKEN)
    get_settings.cache_clear()
    app = create_app()

    async with app.router.lifespan_context(app):
        assert app.state.rawsql_auth_token == TOKEN


def test_main_web_secret_validation_does_not_require_rawsql_token() -> None:
    """The web process boots without a secret for a router it never mounts."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        debug=False,
        session_secret="s" * 32,
        rawsql_auth_token="",
    )

    _validate_secrets(settings)
