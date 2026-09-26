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
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

BASE_URL = os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")
E2E_SECRET_ENV = "APAP_E2E_AUTH_SECRET"

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


@pytest.fixture(scope="session")
def authenticated_state(tmp_path_factory: pytest.TempPathFactory):
    """StorageState path minted once per pytest session via the e2e login CLI (issue #906).

    Calls the importable core of ``scripts/e2e_login.py`` (no subprocess)
    against the live server, caches the resulting storageState under the
    session temp dir, and returns its path for
    ``browser.new_context(storage_state=...)``. Skips — with the same
    semantics as the ad-hoc per-suite preflights it replaces — when the
    secret env is unset or the server has the e2e mock disabled.
    """
    secret = os.environ.get(E2E_SECRET_ENV)
    if secret is None:
        pytest.skip(
            f"{E2E_SECRET_ENV} not set — the OAuth mock cannot authenticate "
            "this test. CI sets the variable; local dev needs to export it "
            "to run authenticated E2E flows."
        )
    import scripts.e2e_login as e2e_login

    out = tmp_path_factory.mktemp("e2e-auth") / "state.json"
    try:
        e2e_login.mint_storage_state(
            base_url=BASE_URL,
            secret_env=E2E_SECRET_ENV,
            email=None,
            out_path=out,
        )
    except e2e_login.E2eLoginError as exc:
        pytest.skip(f"/e2e/login unavailable on {BASE_URL}: {exc}")
    return out


@pytest.fixture
def authenticated_context(_browser: Browser, authenticated_state: Path) -> BrowserContext:
    """A fresh per-test context that starts authenticated from the shared state."""
    ctx = _browser.new_context(base_url=BASE_URL, storage_state=str(authenticated_state))
    yield ctx
    ctx.close()
