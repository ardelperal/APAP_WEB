"""Playwright fixtures for the fail-closed CI smoke suite."""

from __future__ import annotations

import os

import pytest
from minio import Minio
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

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
        add_authorized_user(client, email, "developer", added_by="e2e-ci-seed")


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


