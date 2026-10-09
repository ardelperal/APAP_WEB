"""Playwright fixtures for the fail-closed CI smoke suite."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable

import pytest
from minio import Minio
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from tests.e2e_ci._crud_helpers import (
    animal_form_data,
    csrf_token_from_form,
    entrada_form_data,
)

BASE_URL = os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def browser() -> Browser:
    """Launch Chromium; missing browser support is a hard failure in CI."""
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def browser_context(browser: Browser) -> BrowserContext:
    """Give every smoke test isolated cookies and storage."""
    context = browser.new_context(base_url=BASE_URL)
    yield context
    context.close()


@pytest.fixture
def page(browser_context: BrowserContext) -> Page:
    """Return one browser page for a smoke test."""
    page = browser_context.new_page()
    yield page
    page.close()


@pytest.fixture
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def minio_client() -> Minio:
    """Build a Minio client from APAP_S3_* env vars (available in CI).

    Returns a connected client; raises ``pytest.skip`` when credentials
    are absent (local dev without MinIO).
    """
    endpoint = os.environ.get("APAP_S3_ENDPOINT", "127.0.0.1:9000")
    access_key = os.environ.get("APAP_S3_ACCESS_KEY", "")
    secret_key = os.environ.get("APAP_S3_SECRET_KEY", "")
    secure = os.environ.get("APAP_S3_SECURE", "false").lower() == "true"

    if not access_key or not secret_key:
        pytest.skip("APAP_S3_ACCESS_KEY / APAP_S3_SECRET_KEY not set (MinIO not configured)")

    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


@pytest.fixture(scope="session")
def e2e_db_conn():
    """Connect to the E2E PostgreSQL database.

    The DSN is exported by the CI workflow's app-startup step into
    ``APAP_LOCAL_DB_URL`` (same database the uvicorn app uses).
    Raises ``pytest.skip`` when the env var is absent.
    """
    import psycopg

    dsn = os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        pytest.skip("APAP_LOCAL_DB_URL not set (not running in CI)")

    conn = psycopg.connect(dsn, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def _seed_e2e_default_user() -> None:
    """Seed the default E2E user into the CI database (issue #1073).

    ``GET /e2e/login`` resolves the target email against
    ``usuarios_autorizados`` (the DB is the single allowlist) and mints
    the role read from that row. The CI smoke suite logs in with
    ``APAP_E2E_AUTH_DEFAULT_EMAIL``, so that row must exist in the
    ephemeral Postgres before the login flows run. Uses the application's
    own schema/seed/use-case code — no duplicated DDL. Idempotent.
    """
    dsn = os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        # No DB configured (local run without Postgres): nothing to seed.
        # The app under test must provide its own seeded user.
        return

    from app.core.auth import (
        add_authorized_user,
        ensure_schema_and_seed,
        get_user_by_email,
    )
    from app.core.config import Settings
    from app.core.local_backend.db import LocalPostgresExecutor

    settings = Settings(_env_file=None)
    # Same search_path wiring as app/main.py's lifespan executor, so the
    # seeded row and the app under test resolve the same schema when
    # APAP_LOCAL_DB_SCHEMA is set (latent mismatch removal, issue #1073).
    client = LocalPostgresExecutor(dsn, search_path=settings.local_db_schema or None)
    ensure_schema_and_seed(client, settings)
    email = settings.e2e_auth_default_email
    if get_user_by_email(client, email) is None:
        add_authorized_user(
            client, email, "developer", added_by="00000000-0000-0000-0000-000000000000"
        )
    # Issue #1109 (DOC-01 SLICE 3): optional reader seeding for the
    # contratos-auth e2e gate. Mirrors the ``add_authorized_user``
    # call above and the existing ``APAP_E2E_READER_EMAIL`` pattern
    # in ``tests/e2e/test_cesiones_auth.py`` / ``test_sanidad_auth.py``.
    # When the env var is unset (the default for the e2e CI), no
    # reader row is created and the reader-403 atoms skip cleanly.
    reader_email = os.environ.get("APAP_E2E_READER_EMAIL")
    if reader_email and get_user_by_email(client, reader_email) is None:
        add_authorized_user(
            client, reader_email, "reader",
            added_by="00000000-0000-0000-0000-000000000000",
        )


@pytest.fixture
def e2e_logged_in_browser_context(
    browser: Browser,
    base_url: str,
) -> BrowserContext:
    """Browser context with an authenticated session (E2E auth stub).

    Logs in via ``POST /e2e/login`` using the shared secret and
    ``APAP_E2E_AUTH_DEFAULT_EMAIL``.
    """
    import os

    secret = os.environ["APAP_E2E_AUTH_SECRET"]
    default_email = os.environ.get("APAP_E2E_AUTH_DEFAULT_EMAIL", "e2e@apap.local")

    context = browser.new_context(base_url=base_url)

    # Mint a session by hitting the E2E auth stub endpoint
    login_resp = context.request.get(
        f"{base_url}/e2e/login",
        headers={
            "X-E2E-Secret": secret,
            "X-E2E-Email": default_email,
        },
    )
    assert login_resp.ok, f"E2E login failed: {login_resp.status}"

    yield context
    context.close()


# ---------------------------------------------------------------------------
# Issue #1095 (slice 1 + slice 2): shared fixtures for the failing-closed
# CRUD batteries that now live in ``tests/e2e_ci/``. Derived faithfully
# from the inlined per-test fixtures in
# ``tests/e2e/test_animales_crud.py`` (and the parallel definitions in
# test_entradas_crud.py / test_cesiones_crud.py for
# ``animal_id_factory``). Slice 2 adds ``entrada_id_factory`` (chained
# from ``animal_id_factory``) to back the ``test_entradas_crud.py`` and
# ``test_cesiones_crud.py`` ports.
#
# Fail-closed by contract: this gate suite does not ``pytest.skip`` on
# missing ``APAP_E2E_AUTH_SECRET`` or on a failed login (see the module
# docstring and ``_seed_e2e_default_user`` above). The fixtures here
# honour the same rule — a missing env var raises ``KeyError`` and a
# non-200 /e2e/login becomes a hard failure, never a skip.
# ---------------------------------------------------------------------------


@pytest.fixture
def authenticated_session(
    e2e_logged_in_browser_context: BrowserContext,
    base_url: str,
) -> tuple[Page, str]:
    """Developer-session fixture returning ``(page, csrf_token)``.

    Reuses the existing ``e2e_logged_in_browser_context`` so the
    authentication surface stays in one place, then reissues
    ``/e2e/login`` to capture the ``csrf_token`` from the response
    body (the existing fixture discards the body).

    The csrf_token returned here is the same value the form will
    render as ``<input type="hidden" name="csrf_token" value=...>``
    — both come from the same session payload. Playwright submits
    the hidden field automatically, so form-encoded POSTs through
    the browser do not need the header. PATCH requests
    (``/animales/{id}/chip``) and any JSON POST do need
    ``X-CSRFToken``, and that is the case where this fixture's
    second value matters.

    Raises ``KeyError`` when ``APAP_E2E_AUTH_SECRET`` is unset and
    hard-asserts the /e2e/login response — never ``pytest.skip``.
    """
    context = e2e_logged_in_browser_context
    secret = os.environ["APAP_E2E_AUTH_SECRET"]  # KeyError -> fail closed
    default_email = os.environ.get("APAP_E2E_AUTH_DEFAULT_EMAIL", "e2e@apap.local")

    # Replay /e2e/login through the authenticated context so the
    # csrf_token is captured. The session cookie is already set by
    # ``e2e_logged_in_browser_context``, so this call is idempotent
    # on the session side.
    login_resp = context.request.get(
        f"{base_url}/e2e/login",
        headers={
            "X-E2E-Secret": secret,
            "X-E2E-Email": default_email,
        },
    )
    assert login_resp.ok, (
        f"/e2e/login must return 200 in the e2e_ci suite, got "
        f"{login_resp.status}; the OAuth mock is unreachable."
    )
    payload = login_resp.json()
    csrf_token = payload.get("csrf_token")
    assert isinstance(csrf_token, str) and csrf_token, (
        f"/e2e/login must return a non-empty csrf_token, got {payload!r}."
    )

    page = context.new_page()
    try:
        yield page, csrf_token
    finally:
        page.close()


@pytest.fixture
def animal_id_factory(
    authenticated_session: tuple[Page, str], base_url: str
) -> Callable[[], str]:
    """Return a factory that creates a fresh animal and yields its UUID.

    Derived from the parallel ``animal_id_factory`` fixtures in
    ``tests/e2e/test_entradas_crud.py:111`` and
    ``tests/e2e/test_cesiones_crud.py:130``. Each call visits
    ``/animales/new`` (regression sentinel — the page must render
    with a csrf token), POSTs the shared ``animal_form_data`` payload
    directly to ``/animales`` (the animales form uses ``action=""``,
    so the actual route is reached through the request client), and
    extracts the new animal's UUID from the 303 redirect target.

    Under this gate the helper is FAIL-CLOSED: a non-303 from
    ``POST /animales`` is a hard assertion (the original skipped
    on that branch — the gate's contract forbids skips).
    """
    page, csrf_token = authenticated_session

    def _factory() -> str:
        form_data = animal_form_data(f"ci-host-{uuid.uuid4().hex[:8]}")
        form_page = page.goto(f"{base_url}/animales/new", wait_until="domcontentloaded")
        assert form_page is not None and form_page.status == 200
        csrf_token_from_form(page)  # regression sentinel
        # ``max_redirects=0`` keeps the raw 303 — Playwright's request
        # client follows redirects by default and would otherwise hide
        # the 303 under the final 200 detail page, which makes the
        # ``response.status == 303`` assertion below useless. Slice 2
        # flagged this as the same regression-risk the slice-1
        # animales battery documents in its module docstring.
        response = page.request.post(
            f"{base_url}/animales",
            form={"csrf_token": csrf_token, **form_data},
            max_redirects=0,
        )
        assert response.status == 303, (
            f"animal setup failed: POST /animales did not return 303, "
            f"got {response.status}: {response.text()[:300]!r}. "
            f"The CI database must be writable from the e2e gate."
        )
        animal_id = response.headers.get("location", "").rsplit("/", 1)[-1]
        assert animal_id and not animal_id.endswith("/new") and not animal_id.endswith("/edit"), (
            f"animal setup failed; /animales redirect was "
            f"{response.headers.get('location')!r}."
        )
        return animal_id

    return _factory


@pytest.fixture
def entrada_id_factory(
    authenticated_session: tuple[Page, str],
    animal_id_factory: Callable[[], str],
    base_url: str,
) -> Callable[[], str]:
    """Return a factory that creates a fresh entrada and yields its UUID.

    Slice 2 (issue #1095). Mirrors the
    ``tests/e2e/test_cesiones_crud.py:135`` and
    ``tests/e2e/test_cesiones_conflicts.py:109`` factory, swapping
    the original pytest.skip on a non-303 POST for a hard assertion
    (the gate's contract forbids skips).

    Chains into ``animal_id_factory`` because ``EntradaForm.animal_id``
    is a FK against ``animales`` — without an existing animal, the
    service's ``_validate_references`` raises ``ValueError`` and the
    route answers 422. Each call mints a fresh animal and a fresh
    intake-entry (the latter's UNIQUE natural key on
    ``(animal_id, fecha_entrada)`` guarantees no collision across
    factory invocations within the same test run).

    The factory visits ``/entradas/new`` (regression sentinel — the
    page must render with a csrf token) before POSTing directly to
    ``/entradas`` via the request client, mirroring the slice-1
    animales factory pattern.
    """
    page, csrf_token = authenticated_session

    def _factory() -> str:
        animal_id = animal_id_factory()
        # ``max_redirects=0`` keeps the raw 303 (Playwright's request
        # client follows redirects by default; without the override
        # the assertion below would always see the final 200 detail
        # page and lose the 303 the route emits).
        form_response = page.request.post(
            f"{base_url}/entradas",
            form={"csrf_token": csrf_token, **entrada_form_data(
                animal_id=animal_id,
                fecha_entrada="2024-06-01",
            )},
            max_redirects=0,
        )
        assert form_response.status == 303, (
            f"entrada setup failed: POST /entradas did not return 303, "
            f"got {form_response.status}: {form_response.text()[:300]!r}. "
            f"The CI database must be writable from the e2e gate."
        )
        entrada_id = form_response.headers.get("location", "").rsplit("/", 1)[-1]
        assert (
            entrada_id
            and not entrada_id.endswith("/new")
            and not entrada_id.endswith("/edit")
        ), (
            f"entrada setup failed; /entradas redirect was "
            f"{form_response.headers.get('location')!r}."
        )
        return entrada_id

    return _factory


