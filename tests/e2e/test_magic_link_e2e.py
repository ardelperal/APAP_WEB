"""M3.1 E2E: drive the deployed APAP_WEB magic-link round-trip.

Asserts:
1. /login renders the magic-link form (the fix(m3-login) verification).
2. POST /auth/magic/start returns 200 with status=queued.
3. MailDev receives a message with a verify_url.
4. GET /auth/magic/verify?<token> sets the apap_session cookie.
5. The browser is redirected to /.

The Playwright portion is limited to the /login page render
(verifying the fix(m3-login) form is shown). The round-trip itself
is exercised via httpx against the live app, keeping the test fast
and avoiding the sync/async API friction in the conftest.
"""
from __future__ import annotations

import os

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

from tests.e2e._maildev_helper import read_latest_verify_url

pytestmark = pytest.mark.e2e

BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app(base_url: str) -> None:
    """End-to-end magic-link flow against the deployed app on the same VPS."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # 1. /login renders the magic-link form (fix(m3-login) verification)
            page.goto(f"{base_url}/login", wait_until="domcontentloaded")
            magic_form = page.locator('form[action="/auth/magic/start"]')
            expect(magic_form).to_have_count(
                1,
                timeout=5000,
            ), (
                f"magic-link form not present at {base_url}/login — "
                f"check APAP_AUTH_ENABLE_MAGIC_LINK and APAP_SMTP_HOST in Coolify env"
            )
        finally:
            browser.close()

    # 2-4. Round-trip via httpx. The /auth/magic/start endpoint expects
    # a JSON body (the form's onsubmit JS handler — full UI is M3.2).
    # The verify endpoint accepts the raw token via query string.
    with httpx.Client(base_url=base_url, follow_redirects=False) as client:
        r = client.post(
            "/auth/magic/start",
            json={"email": BOOTSTRAP_EMAIL},
        )
        assert r.status_code == 200, (
            f"POST /auth/magic/start returned {r.status_code}: {r.text[:200]}"
        )
        assert r.json().get("status") == "queued", r.json()

        # 3. MailDev receives the message
        verify_url = read_latest_verify_url(MAILDEV_URL, timeout_seconds=10.0)
        assert "/auth/magic/verify?token=" in verify_url, verify_url

        # 4-5. GET the verify URL; assert apap_session cookie + redirect
        r = client.get(verify_url)
        assert r.status_code in (200, 302), (
            f"GET /auth/magic/verify returned {r.status_code}: {r.text[:200]}"
        )
        cookies = client.cookies
        assert "apap_session" in cookies, (
            f"apap_session cookie not set after verify; got {dict(cookies)}"
        )
        # The verify route redirects to / (302) or renders / (200 with
        # the auth-landing template). Either way, the URL must be /.
        final_path = r.url if r.status_code == 200 else r.headers.get("location", "/")
        assert final_path.rstrip("/") == base_url.rstrip("/"), (
            f"expected redirect to {base_url}, got {final_path}"
        )
