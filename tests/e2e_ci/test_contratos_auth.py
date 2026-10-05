"""E2E auth coverage for the ``/contratos`` slice (DOC-01 SLICE 3, #1109).

Pins the auth gate contract for the contratos surface so the slice-2
route hardening stays green:

1. ``POST /contratos`` without a session -> 302 to /login.
2. ``GET /contratos/{entity_type}/{entity_id}/{tipo}`` without a
   session -> 302 to /login.
3. ``POST /contratos`` with a reader session -> 403 Forbidden.

Mirrors ``tests/e2e/test_cesiones_auth.py`` for the auth-redirect
and reader-403 atoms (the closest established pattern for an
"auth contract of a /slice" e2e test). The shared ``e2e_logged_in_
browser_context`` fixture in ``tests/e2e_ci/conftest.py`` mints a
developer session; the reader fixture below follows the
``APAP_E2E_READER_EMAIL`` pattern documented in
``tests/e2e/test_cesiones_auth.py`` so a CI that does not configure a
reader allowlist account skips cleanly instead of failing.

Live application stack required by CI:
- PostgreSQL via the app's ``LocalPostgresExecutor``
- MinIO with the ``apap-contracts`` bucket
- The FastAPI app started by the ``e2e`` CI job
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page

E2E_SECRET_HEADER = "X-E2E-Secret"


def _e2e_secret() -> str | None:
    return os.environ.get("APAP_E2E_AUTH_SECRET")


# ---------------------------------------------------------------------------
# Reader fixture (mirrors tests/e2e/test_cesiones_auth.py::reader_session)
# ---------------------------------------------------------------------------


@pytest.fixture
def reader_session(
    browser,
    base_url: str,
) -> tuple[Page, str]:
    """A Page with a reader (read-only) session cookie.

    A reader rol can GET the download route (READ_CONTRATOS is in
    ``_LEGACY_READ_MATRIX["reader"]``) but cannot POST to it
    (WRITE_CONTRATOS requires admin/staff or a legacy writer rol).
    This fixture mirrors ``tests/e2e/test_cesiones_auth.py``'s
    reader_session so the test follows the same skip-on-missing
    contract; the optional reader seeding in ``conftest.py``
    provisions the row when ``APAP_E2E_READER_EMAIL`` is configured.
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
        f"{response_reader.status} -- is the account allowlisted and active?"
    )
    payload_reader = response_reader.json()
    reader_csrf = payload_reader.get("csrf_token")
    assert isinstance(reader_csrf, str) and reader_csrf

    if payload_reader.get("rol") != "reader":
        pytest.skip(
            f"e2e reader account {reader_email!r} has rol="
            f"{payload_reader.get('rol')!r}, not 'reader' -- fix the allowlist "
            "row to exercise the 403 branch."
        )

    page = context.new_page()
    yield page, reader_csrf
    context.close()


# ---------------------------------------------------------------------------
# Canonical happy-path payload for POST /contratos.
# ---------------------------------------------------------------------------


def _contrato_form_data() -> dict[str, str]:
    """Build a valid ``ContratoForm`` payload for the auth gate atoms.

    The atoms that target POST /contratos do not exercise the use case
    (they are stopped by the auth gate well before ``generate_contrato``
    is reached). The form values are nevertheless plausible so a
    regression that re-orders the middleware stack -- and lets a
    request slip past the auth gate -- still sees a deterministic 4xx
    from the use case instead of an opaque error.
    """
    return {
        "tipo": "Entrada",
        "entity_type": "entrada",
        "entity_id": "00000000-0000-0000-0000-000000000000",
        "numero_contrato": "CPE2E000",
        "fecha": "2026-10-02",
    }


# --- 1. unauthenticated POST /contratos -> 302 ----------------------------


def test_post_contratos_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """POST /contratos without a session -> 302 to /login (not 403).

    The ``protect_user_facing_routes`` middleware short-circuits before
    ``CsrfMiddleware`` and before ``require_permission`` runs, so an
    unauthenticated POST is redirected to /login. This matches the
    documented middleware ordering in ``app/core/middleware.py`` and
    pins the contract that the auth gate stays outermost on the
    write path. ``max_redirects=0`` pins the RAW redirect response:
    Playwright's ``APIRequestContext`` follows redirects by default,
    so the final response would be the rendered /login (or its 503),
    never the 302 the auth guard issues (issues #1153/#1160).
    """
    response = page.request.post(
        f"{base_url}/contratos",
        max_redirects=0,
        form=_contrato_form_data(),
    )

    assert response.status in (302, 303), (
        f"POST without session must redirect to /login, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
    assert "/login" in response.headers.get("location", ""), (
        f"POST without session must redirect to /login; "
        f"got location: {response.headers.get('location')!r}"
    )


# --- 2. unauthenticated GET /contratos/.../... -> 302 ----------------------


def test_get_download_without_session_redirects_to_login(
    page: Page, base_url: str
) -> None:
    """GET /contratos/{entity_type}/{entity_id}/{tipo} without a session -> /login.

    The download route is gated by ``require_permission(READ_CONTRATOS)``
    on top of ``require_authorized_user``; the auth middleware fires
    first and 302-redirects to /login. ``page.goto`` follows the
    redirect chain automatically, so the final response is the
    rendered /login (200) -- we pin the server-redirect contract via
    ``redirected_from`` rather than the final status (issues #1153 /
    #1160). The 404 for a never-generated contract lives in
    ``tests/e2e_ci/test_contratos_pdf.py``; this atom only pins the
    auth gate, not the 404 body of the route.
    """
    response = page.goto(
        f"{base_url}/contratos/entrada/00000000-0000-0000-0000-000000000000/Entrada",
        wait_until="domcontentloaded",
    )

    assert response is not None
    assert page.url.endswith("/login"), (
        f"GET download without session must end at /login, got: {page.url!r}"
    )
    assert response.request.redirected_from is not None, (
        "GET download must reach /login through a server redirect, "
        "not a client-side bounce"
    )


# --- 3. reader rol cannot POST /contratos -> 403 --------------------------


def test_reader_cannot_post_contratos(
    reader_session: tuple[Page, str],
    base_url: str,
) -> None:
    """POST /contratos with a reader session -> 403 Forbidden.

    The route requires ``WRITE_CONTRATOS`` permission (admin / staff /
    legacy writer). A reader rol is authenticated (valid session, valid
    CSRF token) but lacks the required permission: the RBAC gate
    returns 403 before any port call is made. Skips when the OAuth
    mock cannot mint a reader session (``APAP_E2E_READER_EMAIL``
    unset).
    """
    page, csrf_token = reader_session

    response = page.request.post(
        f"{base_url}/contratos",
        form={"csrf_token": csrf_token, **_contrato_form_data()},
    )

    assert response.status == 403, (
        f"reader rol must get 403 on POST /contratos, got {response.status}: "
        f"{response.text()[:300]!r}"
    )
