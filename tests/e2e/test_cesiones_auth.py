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

    # The mock resolves the session rol from ``usuarios_autorizados``
    # (issue #1073): the target is ``?email=``, and ``?rol=`` is NOT
    # part of its contract. A reader session therefore requires an
    # allowlisted reader account, wired through APAP_E2E_READER_EMAIL.
    reader_email = os.environ.get("APAP_E2E_READER_EMAIL")
    if reader_email is None:
        pytest.skip(
            "APAP_E2E_READER_EMAIL not set: the OAuth mock resolves the rol from "
            "usuarios_autorizados (issue #1073) and cannot mint a reader session "
            "on demand; point APAP_E2E_READER_EMAIL at an allowlisted reader."
        )

    response_reader = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={E2E_SECRET_HEADER: secret},
        params={"email": reader_email},
    )
    assert response_reader.status == 200, (
        f"/e2e/login?email={reader_email!r} must mint the reader session, got "
        f"{response_reader.status} — is the account allowlisted and active?"
    )
    payload_reader = response_reader.json()
    reader_csrf = payload_reader.get("csrf_token")
    assert isinstance(reader_csrf, str) and reader_csrf

    if payload_reader.get("rol") != "reader":
        pytest.skip(
            f"e2e reader account {reader_email!r} has rol="
            f"{payload_reader.get('rol')!r}, not 'reader' — fix the allowlist "
            "row to exercise the 403 branch."
        )

    page = browser_context.new_page()
    return page, reader_csrf


# --- 1. unauthenticated GET /cesiones/new → 302 ---------------------------


def test_get_form_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /cesiones/new without a session → 302 to /login.

    ``require_permission`` fires before the handler and redirects to
    /login. This is the first line of defence for every protected route.
    """
    response = page.goto(f"{base_url}/cesiones/new", wait_until="domcontentloaded")

    _assert_bounced_to_login(page, response, "/cesiones/new")


# --- 2. unauthenticated POST /cesiones → 302 (not 403) --------------------


def test_post_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /cesiones without a session → 302 to /login (not 403).

    CsrfMiddleware fires before the auth dependency, so an unauthenticated
    POST is redirected to /login before the CSRF token is checked. This
    matches the standard FastAPI middleware ordering.

    ``max_redirects=0`` pins the RAW redirect response: Playwright's
    ``APIRequestContext`` follows redirects by default, so the final
    response would be the rendered /login (or its 503), never the 302
    the auth guard issues (issues #1153/#1160).
    """
    # POST without any session cookie or CSRF token.
    response = page.request.post(
        f"{base_url}/cesiones",
        max_redirects=0,
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
