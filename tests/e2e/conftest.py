"""Shared fixtures + collection rules for the Playwright-based E2E tests.

The fixture ``browser_context`` opens one Chromium browser per test
session, creates a fresh context per test, and yields a
``playwright.sync_api.Page``. Tests use the page to navigate, assert
visual properties, fill forms, etc.

The ``pytest_collection_modifyitems`` hook auto-skips the whole
``tests/e2e/`` module if the chromium binary is missing or
``APAP_E2E_SKIP=1`` is set. This keeps CI minimal images green while
letting ``pytest tests/e2e/`` work locally with ``playwright install
chromium``.

The session-scoped ``authenticated_state`` fixture (issue #906) mints a
Playwright storageState via ``scripts/e2e_login.py``. Its skip policy is
deliberately narrow (finding F1 of fix round 1): skip ONLY when the
secret env var is absent or ``/e2e/login`` answers 404 (mock disabled);
a wrong/stale secret (401), an empty server secret (503), or a transport
error propagates so the authenticated suite fails loudly. The fixture is
also TTL-aware (finding F3): the cache re-mints every 240s, under the
server's 300s in-process auth-cache TTL.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import scripts.e2e_login as e2e_login

BASE_URL = os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")
E2E_SECRET_ENV = "APAP_E2E_AUTH_SECRET"
E2E_LOGIN_PATH = "/e2e/login"

# Issue #821: the stepper E2E suite exercises the developer-only
# /devtools pages, which exist only when ``Settings.devtools_enabled``
# is True. The Playwright suite runs against an EXTERNALLY started
# server (CI and local dev export the APAP_* env before launching
# uvicorn), so this default documents the expected environment and
# covers any in-process app construction. It is scoped to tests/e2e
# collection only — production keeps the flag off (default False).
os.environ.setdefault("APAP_DEVTOOLS_ENABLED", "true")


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip the e2e module when chromium is not installed or explicitly disabled."""
    if os.environ.get("APAP_E2E_SKIP") == "1":
        _skip_all(items, "APAP_E2E_SKIP=1")
        return

    # Bare exception by design: this is a probe at collection time —
    # any failure (chromium missing, missing system libs, sandboxed CI)
    # should skip the module rather than crash the whole pytest run.
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        _skip_all(
            items,
            f"chromium binary not available (run: playwright install chromium). {exc}",
        )


def _skip_all(items, reason: str) -> None:
    """Add a skip marker to every test item that lives under tests/e2e/."""
    skip_marker = pytest.mark.skip(reason=reason)
    # ``item.fspath`` is a py.path.local; str() normalises the path with
    # forward slashes so we can match a stable substring regardless of
    # the host OS separator.
    for item in items:
        if "tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def _browser() -> Browser:
    """A session-scoped Chromium browser (one process per pytest run)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def browser_context(_browser: Browser) -> BrowserContext:
    """A fresh browser context per test (isolated cookies, storage)."""
    ctx = _browser.new_context(base_url=BASE_URL)
    yield ctx
    ctx.close()


@pytest.fixture
def page(browser_context: BrowserContext) -> Page:
    """A new Page bound to the per-test browser context."""
    yield browser_context.new_page()


@pytest.fixture
def base_url() -> str:
    """The base URL the test server is reachable at."""
    return BASE_URL


def authenticated_state_skip_reason(exc: BaseException) -> str | None:
    """Classify an e2e-login failure as benign (skip reason) or fatal (None).

    The skip/propagate decision lives in
    :func:`scripts.e2e_login.is_benign_login_failure` (skip ONLY when the
    secret env var is absent or the endpoint answers 404 — mock disabled;
    everything else fails the suite loudly, issue #906 finding F1); this
    wrapper only renders the operator-facing skip message.
    """
    import scripts.e2e_login as e2e_login  # noqa: PLC0415 — lazy, like the fixtures

    if not e2e_login.is_benign_login_failure(exc):
        return None
    if isinstance(exc, e2e_login.MissingSecretError):
        return (
            f"{E2E_SECRET_ENV} not set — the OAuth mock cannot authenticate "
            "this test. CI sets the variable; local dev needs to export it "
            "to run authenticated E2E flows."
        )
    return (
        f"{E2E_LOGIN_PATH} returned 404 on {BASE_URL} — the e2e "
        "auth mock is disabled on this target (e2e_auth_enabled off)."
    )


def _ensure_auth_state_or_skip(cache: e2e_login.AuthStateCache) -> Path:
    """ensure_fresh() with the benign-failure skip policy; fatal errors propagate."""
    import scripts.e2e_login as e2e_login  # noqa: PLC0415 — lazy, like the fixtures

    try:
        return cache.ensure_fresh()
    except e2e_login.E2eLoginError as exc:
        reason = authenticated_state_skip_reason(exc)
        if reason is not None:
            pytest.skip(reason)
        raise  # 401 / 503 / etc: the authenticated suite must FAIL loudly


@pytest.fixture(scope="session")
def authenticated_state_cache(tmp_path_factory: pytest.TempPathFactory) -> e2e_login.AuthStateCache:
    """TTL-aware session cache for the minted storageState (issue #906, F3).

    The server refreshes its 300s in-process auth cache only on
    ``/e2e/login``; this cache re-mints through that endpoint whenever
    its copy is older than 240s (a safety margin under the server TTL),
    so suites longer than ~5 minutes keep working without touching the
    server-side default. ``authenticated_context`` re-checks freshness
    per test; ``authenticated_state`` exposes the session-start path.
    """
    import scripts.e2e_login as e2e_login  # noqa: PLC0415 — lazy, like the fixtures

    out = tmp_path_factory.mktemp("e2e-auth") / "state.json"
    return e2e_login.AuthStateCache(
        base_url=BASE_URL,
        secret_env=E2E_SECRET_ENV,
        out_path=out,
    )


@pytest.fixture(scope="session")
def authenticated_state(authenticated_state_cache: e2e_login.AuthStateCache) -> Path:
    """StorageState path minted via the e2e login CLI (issue #906).

    Returns the cached path from ``authenticated_state_cache`` (mints on
    first use). The per-test freshness guarantee — re-mint every 240s to
    stay under the server's 300s auth-cache TTL, which only ``/e2e/login``
    refreshes — lives in ``authenticated_context``; a direct consumer of
    this session-scoped path gets the state as of session start.

    Skip policy: skip ONLY when the secret env var is absent or the
    endpoint returns 404 (mock disabled). A wrong/stale secret (401), an
    empty server secret (503), or a transport error raises — the suite
    must FAIL loudly, never green-skip (issue #906, finding F1).
    """
    return _ensure_auth_state_or_skip(authenticated_state_cache)


@pytest.fixture
def authenticated_context(_browser: Browser, authenticated_state_cache: e2e_login.AuthStateCache) -> BrowserContext:
    """A fresh per-test context that starts authenticated from the shared state.

    Re-checks the cache's TTL freshness before building the context:
    the server's auth cache expires after 300s and only ``/e2e/login``
    refreshes it, so long suites re-mint every 240s (issue #906, F3).
    The same benign-failure skip policy applies to the per-test re-mint.
    """
    state = _ensure_auth_state_or_skip(authenticated_state_cache)
    ctx = _browser.new_context(base_url=BASE_URL, storage_state=str(state))
    yield ctx
    ctx.close()
