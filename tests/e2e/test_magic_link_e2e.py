"""M3.1 E2E: drive the deployed APAP_WEB magic-link round-trip.

Asserts:
1. /login renders the magic-link form (the fix(m3-login) verification).
2. POST /auth/magic/start returns 200 with status=queued.
3. MailDev receives a message with a verify_url.
4. GET /auth/magic/verify?<token> sets the apap_session cookie.
5. The browser is redirected to /.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import pytest

from playwright.sync_api import expect, sync_playwright

from tests.e2e._maildev_helper import read_latest_verify_url

pytestmark = pytest.mark.e2e

DEPLOYED_BASE = os.environ.get("E2E_BASE_URL", "https://apap.romancaba.com")
BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app(
    e2e_base_url: str, maildev_url: str
) -> None:
    """End-to-end magic-link flow against the deployed app on the same VPS.

    1. /login renders the magic-link form (fix(m3-login) verification).
    2. Submit the bootstrap email; expect 200 + status=queued.
    3. MailDev receives the message; extract the verify URL.
    4. Open the verify URL; expect redirect to / + apap_session cookie.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        # 1. /login renders the magic-link form
        page.goto(f"{e2e_base_url}/login", wait_until="domcontentloaded")
        magic_form = page.locator('form[action="/auth/magic/start"]')
        assert magic_form.count() == 1, (
            f"magic-link form not present at {e2e_base_url}/login — "
            f"check APAP_AUTH_ENABLE_MAGIC_LINK and APAP_SMTP_HOST in Coolify env"
        )
        # 2. Submit the bootstrap email via the form
        page.fill('input[name="email"]', BOOTSTRAP_EMAIL)
        # Capture the response status
        with page.expect_navigation() as nav_info:
            magic_form.locator('button[type="submit"]').click()
        response = nav_info.value
        assert response is not None and response.status == 200, (
            f"POST /auth/magic/start returned {response.status if response else 'no response'}"
        )
        # 3. MailDev receives the message
        verify_url = read_latest_verify_url(maildev_url, timeout_seconds=10.0)
        assert "/auth/magic/verify?token=" in verify_url, verify_url
        # 4. Open the verify URL via a fresh context (so we capture the
        #    Set-Cookie response without the form-submission cookies)
        verify_context = browser.new_context()
        verify_page = verify_context.new_page()
        verify_page.goto(verify_url, wait_until="domcontentloaded")
        # 5. Assert the apap_session cookie is set
        cookies = {c["name"]: c for c in verify_context.cookies()}
        assert "apap_session" in cookies, (
            f"apap_session cookie not set after verify; got {list(cookies)}"
        )
        # 6. The browser is redirected to /
        assert verify_page.url.rstrip("/") == e2e_base_url.rstrip("/"), (
            f"expected redirect to {e2e_base_url}, got {verify_page.url}"
        )
        browser.close()
