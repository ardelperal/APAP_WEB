"""Shared fixtures + collection rules for the Playwright-based E2E tests.

The fixture ``browser_page`` opens one Chromium browser per test
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

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

BASE_URL = os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Skip the e2e module when chromium is not installed or explicitly disabled."""
    if os.environ.get("APAP_E2E_SKIP") == "1":
        _skip_all(items, "APAP_E2E_SKIP=1")
        return

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
    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        if "tests/e2e" in str(item.fspath):
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
