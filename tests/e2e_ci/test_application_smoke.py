"""Fail-closed browser smoke tests against the real CI application process."""

from __future__ import annotations

import os

from playwright.sync_api import BrowserContext, Page


def test_health_exposes_the_running_revision(page: Page, base_url: str) -> None:
    response = page.goto(f"{base_url}/healthz")

    assert response is not None
    assert response.status == 200
    assert response.json() == {
        "status": "ok",
        "app": "APAP_WEB",
        "revision": "development",
    }


def test_e2e_auth_reaches_the_authenticated_home(
    browser_context: BrowserContext,
    base_url: str,
) -> None:
    secret = os.environ["APAP_E2E_AUTH_SECRET"]
    login = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={"X-E2E-Secret": secret},
    )
    assert login.status == 200

    page = browser_context.new_page()
    response = page.goto(f"{base_url}/")

    assert response is not None
    assert response.status == 200
    assert page.url.rstrip("/") == base_url.rstrip("/")


def test_authenticated_animals_route_uses_bootstrapped_postgres(
    browser_context: BrowserContext,
    base_url: str,
) -> None:
    secret = os.environ["APAP_E2E_AUTH_SECRET"]
    login = browser_context.request.get(
        f"{base_url}/e2e/login",
        headers={"X-E2E-Secret": secret},
    )
    assert login.status == 200

    page = browser_context.new_page()
    response = page.goto(f"{base_url}/animales")

    assert response is not None
    assert response.status == 200
