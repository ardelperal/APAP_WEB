"""E2E auth coverage for the ``/cesiones`` slice (INTAKE-03, #41).

Pins the auth gate contract for the cesiones surface:

1. ``GET /cesiones/new`` without a session → 302 to /login.
2. ``POST /cesiones`` without a session → 302 to /login
   (CSRF middleware fires after auth, so unauthenticated POSTs are
   redirected before the token is checked).
3. ``POST /cesiones`` with a reader session → 403 Forbidden.

Fail-closed under the e2e_ci gate (issue #1096, tramo B): the
shared ``authenticated_session`` and reader-account seeding fixtures
live in ``tests/e2e_ci/conftest.py``; the gate's contract reads
``APAP_E2E_AUTH_SECRET`` / ``APAP_E2E_READER_EMAIL`` directly (a
missing variable is a ``KeyError``, never a skip) and the
``_seed_e2e_default_user`` autouse seeds the ``reader`` row in
``usuarios_autorizados`` so the allowlist lookup resolves. The
``tests/e2e/`` version carried four skip branches on
``APAP_E2E_AUTH_SECRET``, ``APAP_E2E_READER_EMAIL``, the
``/login`` 503 final response, and the ``rol != "reader"`` case;
all four are gone — the gate provisions them, and a missing
provision is a failure, not a skip. The empirical answer about the
``/login`` 503 (Google OAuth is not configured under the gate) is
captured in the issue's handoff, not in this assertion.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Page

E2E_SECRET_HEADER = "X-E2E-Secret"


def _assert_bounced_to_login(page: Page, response, origin: str) -> None:
    """Assert an anonymous navigation landed on /login through a server redirect.

    Final-response semantics (issues #1153/#1160): ``page.goto`` returns
    the FINAL response of the redirect chain, so the server-side 302
    surfaces as 200 @ /login when Google OAuth is configured or 503
    @ /login when OAuth is unconfigured (the e2e_ci posture — the
    gate provisions ``/e2e/login`` instead of Google OAuth). The
    ``redirected_from`` predecessor pins the server-redirect
    contract (a JS bounce would not have one) regardless of the
    final status.

    The /login 503 skip branch from the tests/e2e/ version is gone: the gate's
    contract forbids skips, and the 503 final status is a property of the
    OAuth-``/login`` route, not of the auth gate that issued the redirect. The
    landing is therefore asserted as "rendered /login": 200 when Google OAuth
    is configured, or the explicit OAuth-unconfigured 503 payload the CI gate
    produces (it provisions ``/e2e/login`` instead). The payload is checked as
    well, so an unrelated 503 cannot pass as a valid landing.
    """
    assert response is not None
    assert page.url.endswith("/login"), (
        f"{origin} without session should redirect to /login, got: {page.url}"
    )
    assert response.request.redirected_from is not None, (
        f"{origin} must reach /login through a server redirect, not a client-side bounce"
    )
    assert response.status in (200, 503), (
        f"{origin} must land on a rendered /login (200) or the "
        f"OAuth-unconfigured 503, got {response.status}"
    )
    if response.status == 503:
        body = response.text()
        assert "OAuth no est\u00e1 configurado" in body, (
            "the 503 landing must be the OAuth-unconfigured /login payload, "
            f"got: {body[:200]!r}"
        )


@pytest.fixture
def reader_session(
    browser: Browser,
    base_url: str,
) -> tuple[Page, str]:
    """A Page with a reader (read-only) session cookie.

    The reader rol cannot POST to /cesiones (requires WRITE_CESIONES
    permission). This fixture mimics the authenticated flow but
    targets the allowlisted reader account so the RBAC gate fires
    before any port call.

    FAIL-CLOSED under the e2e_ci gate (issue #1096, tramo B):
    ``APAP_E2E_AUTH_SECRET`` and ``APAP_E2E_READER_EMAIL`` are read
    via ``os.environ[...]`` — a missing variable is a ``KeyError``
    and propagates as a hard failure (the gate provisions both).
    The allowlist row is seeded by ``_seed_e2e_default_user`` in
    ``tests/e2e_ci/conftest.py`` so the ``?email=`` lookup against
    ``usuarios_autorizados`` returns the ``reader`` rol and the
    final ``assert payload_reader.get("rol") == "reader"`` succeeds
    — a different rol means the seeded row is wrong and the gate
    is broken, which is what the assert surfaces.
    """
    secret = os.environ["APAP_E2E_AUTH_SECRET"]  # KeyError -> fail closed
    reader_email = os.environ["APAP_E2E_READER_EMAIL"]  # KeyError -> fail closed

    # Fresh browser context so the reader cookie is isolated from the
    # shared ``e2e_logged_in_browser_context`` fixture (developer).
    context = browser.new_context(base_url=base_url)

    response_reader = context.request.get(
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

    # The seed in ``_seed_e2e_default_user`` inserts the reader row
    # with rol='reader'; anything else means the allowlist is
    # misconfigured and the 403 atom would not exercise the intended
    # branch. Hard assert — never skip.
    assert payload_reader.get("rol") == "reader", (
        f"e2e reader account {reader_email!r} has rol="
        f"{payload_reader.get('rol')!r}, not 'reader' — fix the allowlist "
        "row to exercise the 403 branch."
    )

    page = context.new_page()
    try:
        yield page, reader_csrf
    finally:
        context.close()


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
