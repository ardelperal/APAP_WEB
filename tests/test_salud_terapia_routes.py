"""Route tests for the terapia create/update error contract (issue #1070).

The routes used to catch bare ``Exception`` and present ANY failure as
"backend unreachable" (503): a ``TypeError`` or ``KeyError`` from the
service's own code reached the operator as a network problem, and the
log did not name the real type. The contract is now:

- ``ValueError`` (service validation) → 422 form re-render.
- ``BackendError`` (transport) → 503 + ``salud.terapia.backend_error``.
- Anything else (programming bug) propagates to the 500 handler.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from app.core.data_access import BackendError
from app.core.di.local_postgres_di import get_local_postgres_executor_dep
from app.core.session import session_cookie_name, write_session
from app.main import app as _app
from app.modules.salud import service as salud_service


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-salud",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _form_data() -> dict[str, str]:
    return {
        "animal_id": "a-1",
        "voluntario_id": "v-1",
        "fecha": "2026-03-10",
    }


@pytest.fixture
def override_client():
    """Override the SQL executor dependency with a silent spy."""

    class _Spy:
        def execute_sql(self, *args: object, **kwargs: object) -> list[dict[str, Any]]:
            raise AssertionError("the route must delegate to the service")

        def close(self) -> None:
            return None

    spy = _Spy()
    _app.dependency_overrides[get_local_postgres_executor_dep] = lambda: spy
    yield spy
    _app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


def _boom(kind: type[Exception], monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        if kind is BackendError:
            raise kind(503, {"error": "forced failure (issue #1070)"})
        raise kind("forced failure (issue #1070)")

    monkeypatch.setattr(salud_service, "create_terapia", _raise)


async def test_value_error_from_service_renders_form_with_422(
    client: httpx.AsyncClient,
    override_client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    _boom(ValueError, monkeypatch)

    response = await make_post(client)

    assert response.status_code == 422, response.text
    assert "No se pudo guardar la terapia" in response.text


async def test_backend_error_from_service_renders_503_and_logs(
    client: httpx.AsyncClient,
    override_client: object,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _login_as_key_user(client)
    _boom(BackendError, monkeypatch)

    with caplog.at_level(logging.INFO, logger="app"):
        response = await make_post(client)

    assert response.status_code == 503, response.text
    assert "No se pudo contactar con el backend" in response.text
    events = [r for r in caplog.records if "salud.terapia.backend_error" in r.getMessage()]
    assert events, "a BackendError must emit salud.terapia.backend_error"


async def test_type_error_from_service_is_not_masked_as_backend_down(
    client: httpx.AsyncClient,
    override_client: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #1070: a programming bug must reach the 500 handler, never
    the "backend unreachable" 503."""
    _login_as_key_user(client)
    _boom(TypeError, monkeypatch)

    with pytest.raises(TypeError, match="forced failure"):
        await make_post(client)


async def make_post(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/terapias",
        data=_form_data(),
        headers={"X-CSRFToken": "test-csrf-token-salud"},
        follow_redirects=False,
    )
