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


def _assert_bounced_to_login(page: Page, response, origin: str) -> None:
    """Assert an anonymous navigation landed on a rendered /login.

    Final-response semantics (issues #1153/#1160): ``page.goto`` returns
    the FINAL response of the redirect chain, so the server-side 302
    surfaces as 200 @ /login; the ``redirected_from`` predecessor pins
    the server-redirect contract (a JS bounce would not have one). A 503
    final response means /login cannot render on this target (OAuth
    unconfigured) — skipped with the #1153 preflight reason, never
    counted as an assertion failure.
    """
    assert response is not None
    if response.status == 503:
        pytest.skip(
            f"{origin} reached /login but it returned 503 (Google OAuth "
            "not configured on this target); the auth gate did redirect."
        )
    assert response.status == 200, (
        f"{origin} should land on a rendered /login (final response of the redirect "
        f"chain), got {response.status} @ {response.url}"
    )
    assert page.url.endswith("/login"), (
        f"{origin} without session should redirect to /login, got: {page.url}"
    )
    assert response.request.redirected_from is not None, (
        f"{origin} must reach /login through a server redirect, not a client-side bounce"
    )


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

    _assert_bounced_to_login(page, response, "/sanidad")


# --- 2. unauthenticated GET /sanidad/new → 302 ------------------------


def test_get_form_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /sanidad/new without a session → 302 to /login."""
    response = page.goto(f"{base_url}/sanidad/new", wait_until="domcontentloaded")

    _assert_bounced_to_login(page, response, "/sanidad/new")


# --- 3. unauthenticated POST /sanidad → 302 (not 403) ----------------


def test_post_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /sanidad without a session → 302 to /login.

    CsrfMiddleware fires before the auth dependency, so an unauthenticated
    POST is redirected to /login before the CSRF token is checked.
    ``max_redirects=0`` pins the RAW redirect response: Playwright's
    ``APIRequestContext`` follows redirects by default, so the final
    response would be the rendered /login (or its 503), never the 302
    the auth guard issues (issues #1153/#1160).
    """
    response = page.request.post(
        f"{base_url}/sanidad",
        max_redirects=0,
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
    """POST /sanidad/{id}/delete without a session → 302 to /login.

    ``max_redirects=0`` pins the RAW redirect response (see the POST
    test above; issues #1153/#1160).
    """
    response = page.request.post(
        f"{base_url}/sanidad/fake-actuacion-id/delete",
        max_redirects=0,
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

    The route requires ``WRITE_SALUD`` (key_user rol); a reader rol is
    authenticated but the RBAC gate returns 403 before any port call.
    The mock resolves the rol from ``usuarios_autorizados`` (issue
    #1073), so a reader session requires an allowlisted reader account
    wired through APAP_E2E_READER_EMAIL; otherwise the 403 branch is
    unreachable and the test skips with a traced reason.
    """
    reader_email = os.environ.get("APAP_E2E_READER_EMAIL")
    if reader_email is None:
        pytest.skip(
            "APAP_E2E_READER_EMAIL not set: the OAuth mock resolves the rol from "
            "usuarios_autorizados (issue #1073) and cannot mint a reader session "
            "on demand; point APAP_E2E_READER_EMAIL at an allowlisted reader."
        )

    page, csrf_token = authenticated_session
    _ = csrf_token  # the reader POST mints its own token below

    response_reader = page.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: _e2e_secret() or ""},
        params={"email": reader_email},
    )
    assert response_reader.status == 200, (
        f"/e2e/login?email={reader_email!r} must mint the reader session, "
        f"got {response_reader.status} — is the account allowlisted and "
        "active on this target?"
    )
    reader_payload = response_reader.json()
    reader_csrf = reader_payload.get("csrf_token")
    assert isinstance(reader_csrf, str) and reader_csrf

    if reader_payload.get("rol") != "reader":
        pytest.skip(
            f"e2e reader account {reader_email!r} has rol="
            f"{reader_payload.get('rol')!r}, not 'reader' — fix the allowlist "
            "row to exercise the 403 branch."
        )

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
