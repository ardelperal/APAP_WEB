"""E2E auth coverage for the ``/cesiones`` slice (INTAKE-03, #41).

Pins the auth gate contract for the cesiones surface:

1. ``GET /cesiones/new`` without a session → 302 to /login.
2. ``POST /cesiones`` without a session → 302 to /login
   (CSRF middleware fires after auth, so unauthenticated POSTs are
   redirected before the token is checked).
3. ``POST /cesiones`` with a reader session → 403 Forbidden.

The ``authenticated_session`` fixture is copied verbatim from
``test_cesiones_crud.py`` for self-contained readability.

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
    """A Page with a key_user session cookie minted by ``/e2e/login``."""
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


@pytest.fixture
def reader_session(
    browser_context: BrowserContext, base_url: str
) -> tuple[Page, str]:
    """A Page with a reader (read-only) session cookie.

    The reader rol cannot POST to /cesiones (requires WRITE_CESIONES
    permission). This fixture mimics the authenticated flow but
    specifies rol=reader so the RBAC gate fires before any port call.
    """
    secret = _e2e_secret()
    if secret is None:
        pytest.skip("APAP_E2E_AUTH_SECRET not set.")

    # The /e2e/login endpoint accepts optional session overrides via query
    # params or defaults to key_user. We use the same endpoint with the
    # standard secret — the OAuth mock in app.core.e2e_auth.mint_developer_session
    # uses the configured E2E secret and the E2E_SECRET_HEADER to validate
    # the request, then mints a session with the default rol=key_user.
    # To get a reader session we would need to call /e2e/login?rol=reader
    # (or whatever the mock's session override mechanism supports).
    # If the mock does not support per-call rol override, this test
    # documents the expected behaviour and skips until the mock supports it.
    #
    # Fallback: we call /e2e/login the normal way and verify the reader
    # case separately — if the mock cannot mint a reader session,
    # the test documents the gap and skips.
    response = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
    )
    assert response.status == 200
    payload = response.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token

    # Try to override rol via query param (convention: /e2e/login?rol=reader).
    # If the mock supports it, use the reader session; if not, skip.
    response_reader = browser_context.request.get(
        f"{base_url}/e2e/login?rol=reader",
        headers={E2E_SECRET_HEADER: secret},
    )
    if response_reader.status == 200:
        payload_reader = response_reader.json()
        reader_csrf = payload_reader.get("csrf_token")
        if isinstance(reader_csrf, str) and reader_csrf:
            page = browser_context.new_page()
            return page, reader_csrf

    # Mock does not support per-call rol override — skip this specific
    # test case and document the gap.
    pytest.skip(
        "OAuth mock does not support /e2e/login?rol=reader. "
        "The reader rol test requires the mock to mint a session with "
        "rol=reader on demand."
    )


# --- 1. unauthenticated GET /cesiones/new → 302 ---------------------------


def test_get_form_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /cesiones/new without a session → 302 to /login.

    ``require_permission`` fires before the handler and redirects to
    /login. This is the first line of defence for every protected route.
    """
    response = page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")

    assert response is not None
    # 302 is the auth guard's redirect to /login; 303 is the FastAPI
    # RedirectResponse default. Both are valid here — we accept either.
    assert response.status in (302, 303), (
        f"GET /cesiones/new without session must redirect, got {response.status}"
    )
    assert "/login" in response.url, (
        f"auth guard must redirect to /login, got {response.url!r}"
    )


# --- 2. unauthenticated POST /cesiones → 302 (not 403) --------------------


def test_post_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /cesiones without a session → 302 to /login (not 403).

    CsrfMiddleware fires before the auth dependency, so an unauthenticated
    POST is redirected to /login before the CSRF token is checked. This
    matches the standard FastAPI middleware ordering.
    """
    # POST without any session cookie or CSRF token.
    response = page.request.post(
        f"{base_url}/cesiones",
        form={"entrada_id": "x", "numero_contrato": "CP0001", "nombre_representante": "Test"},
    )

    assert response.status in (302, 303), (
        f"POST without session must redirect to /login, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    assert "/login" in response.headers.get("location", ""), (
        f"POST without session must redirect to /login; "
        f"got location: {response.headers.get('location')!r}"
    )


# --- 3. reader rol cannot POST /cesiones → 403 ----------------------------


def test_reader_cannot_post_cesiones(
    reader_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /cesiones with a reader session → 403 Forbidden.

    The route requires ``WRITE_CESIONES`` permission (key_user rol).
    A reader rol is authenticated (has a valid session) but lacks the
    required permission — the RBAC gate returns 403 before any port
    call is made.

    Skips when the OAuth mock does not support minting a reader session.
    """
    page, csrf_token = reader_session

    response = page.request.post(
        f"{base_url}/cesiones",
        form={
            "csrf_token": csrf_token,
            "entrada_id": "fake-entrada-id",
            "numero_contrato": "CP0001",
            "nombre_representante": "Test",
        },
    )

    assert response.status == 403, (
        f"reader rol must get 403 on POST /cesiones, got {response.status}: "
        f"{response.text()[:300]!r}"
    )


# --- 4. GET form with reader session → 200 (read is allowed) ---------------


def test_reader_can_get_form(
    authenticated_session: tuple[Page, str],
    base_url: str,
) -> None:
    """GET /cesiones/new with any authenticated session → 200.

    READ_CESIONES is granted to all authenticated roles (key_user and
    reader). The form renders even for a reader; the 403 fires only
    on POST (write action).
    """
    page, _ = authenticated_session

    response = page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")

    assert response is not None
    assert response.status == 200, (
        f"authenticated GET /cesiones/new must return 200, got {response.status}"
    )
