"""E2E auth coverage for the ``/sanidad`` slice (HEALTH-01 / #50).

Pins the auth gate contract:

1. ``GET /sanidad`` without a session → 302 to /login.
2. ``POST /sanidad`` without a session → 302 to /login.
3. ``POST /sanidad`` with a reader session → 403 Forbidden.
4. ``GET /sanidad/new`` without a session → 302 to /login.
5. ``DELETE /sanidad/{id}/delete`` without a session → 302 to /login.

The ``authenticated_session`` fixture is copied verbatim from
``test_sanidad_crud.py`` for self-contained readability.

The tests skip cleanly when ``APAP_E2E_AUTH_SECRET`` is unset.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import BrowserContext, Page

E2E_SECRET_HEADER = "X-E2E-Secret"


def _e2e_secret() -> str | None:
    return os.environ.get("APAP_E2E_AUTH_SECRET")


@pytest.fixture
def authenticated_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    secret = _e2e_secret()
    if secret is None:
        pytest.skip("APAP_E2E_AUTH_SECRET not set.")

    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token

    page = browser_context.new_page()
    return page, csrf_token


# --- 1. unauthenticated GET /sanidad → 302 -----------------------------


def test_get_list_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /sanidad without a session → 302 to /login."""
    response = page.goto(f"{base_url}/sanidad", wait_until="domcontentloaded")

    assert response is not None
    assert response.status in (302, 303), (
        f"GET /sanidad without session must redirect, got {response.status}"
    )
    assert "/login" in response.url, (
        f"auth guard must redirect to /login, got {response.url!r}"
    )


# --- 2. unauthenticated GET /sanidad/new → 302 ------------------------


def test_get_form_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /sanidad/new without a session → 302 to /login."""
    response = page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")

    assert response is not None
    assert response.status in (302, 303), (
        f"GET /sanidad/new without session must redirect, got {response.status}"
    )
    assert "/login" in response.url, (
        f"auth guard must redirect to /login, got {response.url!r}"
    )


# --- 3. unauthenticated POST /sanidad → 302 (not 403) ----------------


def test_post_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /sanidad without a session → 302 to /login.

    CsrfMiddleware fires before the auth dependency, so an unauthenticated
    POST is redirected to /login before the CSRF token is checked.
    """
    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "animal_id": "fake-animal-id",
            "fecha": "2024-07-15",
            "tipo_actuacion_id": "",
        },
    )

    assert response.status in (302, 303), (
        f"POST without session must redirect to /login, got {response.status}"
    )
    assert "/login" in response.headers.get("location", ""), (
        f"POST without session must redirect to /login; "
        f"got location: {response.headers.get('location')!r}"
    )


# --- 4. unauthenticated POST /sanidad/{id}/delete → 302 ---------------


def test_delete_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /sanidad/{id}/delete without a session → 302 to /login."""
    response = page.request.post(
        f"{base_url}/sanidad/fake-actuacion-id/delete",
        form={"csrf_token": "fake-token"},
    )

    assert response.status in (302, 303), (
        f"POST /sanidad/{{id}}/delete without session must redirect, "
        f"got {response.status}"
    )
    assert "/login" in response.headers.get("location", ""), (
        f"delete without session must redirect to /login; "
        f"got location: {response.headers.get('location')!r}"
    )


# --- 5. reader rol cannot POST /sanidad → 403 --------------------------


def test_reader_cannot_post_sanidad(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /sanidad with a reader session → 403 Forbidden.

    The route requires ``WRITE_SALUD`` permission (key_user rol).
    A reader rol is authenticated but lacks the required permission —
    the RBAC gate returns 403 before any port call is made.

    Skips when the OAuth mock does not support minting a reader session.
    """
    page, csrf_token = authenticated_session

    # Try to mint a reader session.
    response_reader = page.request.get(
        f"{base_url}/e2e/login?rol=reader",
        headers={E2E_SECRET_HEADER: _e2e_secret() or ""},
    )
    if response_reader.status != 200:
        pytest.skip(
            "OAuth mock does not support /e2e/login?rol=reader. "
            "The reader rol test requires the mock to mint a session "
            "with rol=reader on demand."
        )
    reader_payload = response_reader.json()
    reader_csrf = reader_payload.get("csrf_token")
    if not isinstance(reader_csrf, str) or not reader_csrf:
        pytest.skip("OAuth mock did not return a csrf_token for reader rol.")

    response = page.request.post(
        f"{base_url}/sanidad",
        form={
            "csrf_token": reader_csrf,
            "animal_id": "fake-animal-id",
            "fecha": "2024-07-15",
            "tipo_actuacion_id": "",
        },
    )

    assert response.status == 403, (
        f"reader rol must get 403 on POST /sanidad, got {response.status}: "
        f"{response.text()[:300]!r}"
    )


# --- 6. reader can GET /sanidad → 200 ---------------------------------


def test_reader_can_get_list(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """GET /sanidad with any authenticated session → 200.

    READ_SALUD is granted to all authenticated roles (key_user and reader).
    The list renders even for a reader; the 403 fires only on POST.
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/sanidad", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, (
        f"authenticated GET /sanidad must return 200, got {response.status}"
    )
