"""Tests for the CSRF middleware (PR-5B2, T-5B.13).

Spec coverage:
- REQ-AH-8 — POST/PUT/PATCH/DELETE require a valid CSRF token via
  header OR form field. Missing/wrong tokens are 403. GET bypasses.
- REQ-AH-10 — Settings.csrf_enabled=False short-circuits the check.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session


class _AnonymousSpy:
    """InsForge stand-in that lets the request reach the route handler."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        if "RETURNING" in query or "INSERT" in query:
            return [
                {
                    "id": "spy-1",
                    "NCHIP": "985112004409871",
                    "NombreAnimal": "Spy",
                    "Especie": "CANINA",
                    "Sexo": "H",
                    "FNacimiento": "2023-04-12",
                    "activo": True,
                }
            ]
        return [{"id": "spy-1"}]

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        return lambda *args, **kwargs: None


@pytest.fixture
def _bypass_insforge(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app, get_insforge_client

    spy = _AnonymousSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    monkeypatch.setattr(
        "app.modules.animals.routes.get_insforge_client_dep", lambda: spy
    )
    yield
    app.dependency_overrides.pop(get_insforge_client, None)


def _login(
    client: httpx.AsyncClient,
    *,
    csrf_token: str = "test-csrf-token",
) -> str:
    settings = get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": csrf_token,
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)
    return csrf_token


def _animal_form_data() -> dict[str, str]:
    return {
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
    }


# --- happy path -----------------------------------------------------------


async def test_post_with_header_token_passes_csrf(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """POST with ``X-CSRFToken`` header matching the session token -> non-403."""
    _login(client)

    response = await client.post(
        "/animales",
        headers={"X-CSRFToken": "test-csrf-token"},
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code != 403, (
        f"middleware rejected a valid header token; body={response.text!r}"
    )


async def test_post_with_form_field_token_passes_csrf(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """POST with ``csrf_token`` form field matching the session -> non-403."""
    _login(client)

    response = await client.post(
        "/animales",
        data={**_animal_form_data(), "csrf_token": "test-csrf-token"},
        follow_redirects=False,
    )

    assert response.status_code != 403, (
        f"middleware rejected a valid form-field token; body={response.text!r}"
    )


# --- sad path -------------------------------------------------------------


async def test_post_without_token_is_rejected_with_403(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """POST with no token at all (no header, no form field) -> 403."""
    _login(client)

    response = await client.post(
        "/animales",
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code == 403
    body = response.json()
    assert "csrf" in body.get("error", "").lower()


async def test_post_with_wrong_token_is_rejected_with_403(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """POST with a token that doesn't match the session -> 403."""
    _login(client, csrf_token="real-token")

    response = await client.post(
        "/animales",
        headers={"X-CSRFToken": "attacker-token"},
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code == 403


# --- adversarial ----------------------------------------------------------


async def test_post_with_session_a_cookie_and_session_b_token_is_rejected(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """Cross-session token replay -> 403 (REQ-AH-8 adversarial scenario)."""
    _login(client, csrf_token="session-A-token")

    response = await client.post(
        "/animales",
        headers={"X-CSRFToken": "session-B-token"},
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code == 403


async def test_post_with_session_without_csrf_token_field_is_rejected(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """A session that predates PR-5B (no csrf_token field) -> 403."""
    settings = get_settings()
    legacy_token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), legacy_token)

    response = await client.post(
        "/animales",
        headers={"X-CSRFToken": "any-token"},
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code == 403


# --- safe methods ---------------------------------------------------------


async def test_get_request_bypasses_csrf_check(
    client: httpx.AsyncClient, _bypass_insforge: None
) -> None:
    """GET requests bypass CSRF entirely (RFC 7231 safe methods)."""
    response = await client.get("/animales", follow_redirects=False)
    assert response.status_code != 403


# --- feature flag ---------------------------------------------------------


async def test_csrf_disabled_feature_flag_skips_middleware(
    client: httpx.AsyncClient, _bypass_insforge: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``APAP_CSRF_ENABLED=false``, the middleware short-circuits."""
    from app.core import config as config_module

    def patched_get_settings():
        return config_module.Settings().model_copy(update={"csrf_enabled": False})

    monkeypatch.setattr(config_module, "get_settings", patched_get_settings)

    response = await client.post(
        "/animales",
        data=_animal_form_data(),
        follow_redirects=False,
    )

    assert response.status_code != 403


# --- placeholder logging (T-5B.27) ----------------------------------------


async def test_csrf_rejection_emits_warning_log(
    client: httpx.AsyncClient, _bypass_insforge: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A rejected POST logs a ``csrf.rejected`` warning (T-5B.27 placeholder)."""
    _login(client)

    with caplog.at_level("WARNING", logger="app.core.csrf"):
        response = await client.post(
            "/animales",
            data=_animal_form_data(),
            follow_redirects=False,
        )

    assert response.status_code == 403
    assert any("csrf.rejected" in rec.message for rec in caplog.records), (
        f"expected a csrf.rejected warning, got: {[r.message for r in caplog.records]}"
    )
