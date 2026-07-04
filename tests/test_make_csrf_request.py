"""Tests for the ``make_csrf_request`` test helper (PR-5B2, T-5B.9/T-5B.10)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session
from tests.conftest import auth_reval_rows, make_csrf_request


class _PassThroughSpy:
    """InsForge stand-in that returns plausible data so the handler completes."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        _reval = auth_reval_rows(query, params)
        if _reval is not None:
            return _reval
        if "RETURNING" in query or "INSERT INTO animales" in query:
            return [
                {
                    "id": "animal-spy-1",
                    "NCHIP": params[0] if params else "spy",
                    "NombreAnimal": "Spy",
                    "Especie": "CANINA",
                    "Sexo": "H",
                    "FNacimiento": "2023-04-12",
                    "activo": True,
                }
            ]
        return [{"id": "spy-1"}]

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        # Strict mode: unmocked methods surface as test failures (see
        # tests/test_all_post_forms_have_csrf_input.py for the rationale).
        raise NotImplementedError(
            f"_AnonymousSpy.{name} is not mocked. Add an explicit method "
            f"to the spy in this test instead of relying on no-op fallback."
        )


@pytest.fixture
def _bypass_insforge_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app, get_insforge_client

    spy = _PassThroughSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    monkeypatch.setattr(
        "app.modules.animals.routes.get_insforge_client_dep", lambda: spy
    )
    yield
    app.dependency_overrides.pop(get_insforge_client, None)


def _login_as_key_user(
    client: httpx.AsyncClient,
    *,
    csrf_token: str | None = None,
) -> str:
    settings = get_settings()
    payload: dict[str, Any] = {
        "email": "ana@example.com",
        "rol": "key_user",
        "user_id": "u-ana",
        "is_authorized": True,
    }
    payload["csrf_token"] = csrf_token or "session-token-for-tests"
    cookie = write_session(payload, secret=settings.session_secret)
    client.cookies.set(session_cookie_name(), cookie)
    return payload["csrf_token"]


async def test_make_csrf_request_attaches_token_from_session_cookie(
    client: httpx.AsyncClient, _bypass_insforge_dependency: None
) -> None:
    """When the client carries a session with ``csrf_token``, the helper attaches it."""
    _login_as_key_user(client)

    response = await make_csrf_request(
        client,
        "POST",
        "/animales",
        form_data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
    )

    assert response.status_code != 403


async def test_make_csrf_request_without_session_cookie_is_rejected(
    client: httpx.AsyncClient, _bypass_insforge_dependency: None
) -> None:
    """When the client has no session, the helper cannot attach a token -> 302/403."""
    response = await make_csrf_request(
        client,
        "POST",
        "/animales",
        form_data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
    )

    assert response.status_code in {302, 403}


async def test_make_csrf_request_explicit_token_override(
    client: httpx.AsyncClient, _bypass_insforge_dependency: None
) -> None:
    """Explicit ``csrf_token=`` overrides the session read."""
    _login_as_key_user(client, csrf_token="session-A-token")

    response = await make_csrf_request(
        client,
        "POST",
        "/animales",
        csrf_token="session-B-token",
        form_data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
    )

    assert response.status_code == 403


async def test_make_csrf_request_attaches_token_to_form_data_too(
    client: httpx.AsyncClient, _bypass_insforge_dependency: None
) -> None:
    """When ``form_data`` is given, the helper ALSO adds the token to the form."""
    _login_as_key_user(client, csrf_token="form-path-token")

    response = await make_csrf_request(
        client,
        "POST",
        "/animales",
        form_data={
            "NCHIP": "985112004409871",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
        },
    )

    assert response.status_code != 403


async def test_make_csrf_request_get_request_is_not_token_gated(
    client: httpx.AsyncClient, _bypass_insforge_dependency: None
) -> None:
    """GET requests bypass CSRF entirely (SAFE_METHODS)."""
    response = await make_csrf_request(client, "GET", "/animales")
    assert response.status_code != 403
