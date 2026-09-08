"""Playwright fixtures for the fail-closed CI smoke suite."""

from __future__ import annotations

import os

import pytest
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
