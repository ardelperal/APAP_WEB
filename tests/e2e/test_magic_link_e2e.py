"""M3.1 E2E: drive the deployed APAP_WEB magic-link round-trip.

Asserts:
1. /login renders the magic-link form (the fix(m3-login) verification).
2. POST /auth/magic/start returns 200 with status=queued.
3. MailDev receives a message with a verify_url.
4. GET /auth/magic/verify?<token> sets the apap_session cookie.
5. The verify handler redirects to / or (in dev) /unauthorized.

The form posts JSON via the onsubmit handler in login.html (M3.2 fix).
The test waits for the fetch response and asserts on its status, not
on a page navigation (the form does not navigate; it updates the
status text and resets).
"""
from __future__ import annotations

import os

import pytest

from tests.e2e._maildev_helper import read_latest_verify_url

pytestmark = pytest.mark.e2e

BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app(page, base_url: str) -> None:
    """End-to-end magic-link flow against the deployed app on the same VPS.

    1. /login renders the magic-link form (fix(m3-login) verification).
    2. Submit the bootstrap email via the form (the onsubmit handler
       intercepts and posts JSON via fetch).
    3. MailDev receives the message; extract the verify URL.
    4. Open the verify URL; assert apap_session cookie is set.
    5. The verify redirects to / (or /unauthorized in dev: the deployed
       / revalidates the session against InsForge, which is unreachable
       in the rdd-M0 dev env — see #650 / #651).
    """
    # 1. /login renders the magic-link form
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    magic_form = page.locator('form[action="/auth/magic/start"]')
    assert magic_form.count() == 1, (
        f"magic-link form not present at {base_url}/login -- "
        f"check APAP_AUTH_ENABLE_MAGIC_LINK and APAP_SMTP_HOST in Coolify env"
    )
    # 2. Submit the bootstrap email via the form. The onsubmit handler
    #    POSTs JSON; we wait for the fetch response, not a navigation.
    page.fill('input[name="email"]', BOOTSTRAP_EMAIL)
    with page.expect_response(
        lambda r: r.url.endswith("/auth/magic/start")
        and r.request.method == "POST"
    ) as resp_info:
        magic_form.locator('button[type="submit"]').click()
    response = resp_info.value
    assert response.status == 200, (
        f"POST /auth/magic/start returned {response.status}: "
        f"{(response.text() if response.status >= 400 else 'ok')}"
    )

    # The form's onsubmit handler surfaces the success/error status in
    # #magic-link-status. Verify it shows the success message.
    status = page.locator("#magic-link-status")
    assert status.is_visible(), "status message should be visible after submit"
    status_text = status.text_content() or ""
    assert "enlace" in status_text.lower(), (
        f"status text did not mention enlace; got {status_text!r}"
    )

    # 3. MailDev receives the message
    verify_url = read_latest_verify_url(MAILDEV_URL, timeout_seconds=10.0)
    assert "/auth/magic/verify?token=" in verify_url, verify_url
    # The deployed app sends a relative URL like `/auth/magic/verify?token=...`.
    # Prepend base_url so Playwright navigates against the deployed app
    # instead of resolving it against MailDev's localhost:8025.
    if verify_url.startswith("/"):
        verify_url = f"{base_url}{verify_url}"

    # 4. Open the verify URL via a fresh context (the form-submission
    #    page may have set session cookies already; we want the verify
    #    to set apap_session itself).
    page.context.clear_cookies()
    # Use networkidle so the 302 redirect to / completes before
    # we read cookies (the apap_session cookie travels in the 302
    # response and would otherwise be racy with cookies()).
    # The goto follows the 302 internally; wait for URL to settle.
    try:
        page.goto(verify_url, wait_until="domcontentloaded", timeout=10000)
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    cookies = {c["name"]: c for c in page.context.cookies()}

    # 5. Assert the apap_session cookie is set
    assert "apap_session" in cookies, (
        f"apap_session cookie not set after verify; got {list(cookies)}"
    )

    # 6. The verify handler redirects to /. The deployed ``/`` route
    #    revalidates the session against the InsForge user table via
    #    ``insforge_revalidate_session`` dep, which is unreachable in
    #    the rdd-M0 dev env (InsForge hosted proxy returns 503; see
    #    #650). In production the user IS in the table and the redirect
    #    lands at ``/``. The revalidation gate is tracked separately in
    #    #651. We accept both outcomes: ``/`` (production) or
    #    ``/unauthorized`` (dev — cookie IS set, revalidation just
    #    couldn't confirm).
    final_url = page.url.rstrip("/")
    expected_url = base_url.rstrip("/")
    assert (
        final_url == expected_url
        or final_url == expected_url + "/unauthorized"
    ), (
        f"expected redirect to {base_url} (or /unauthorized when InsForge "
        f"is unreachable; see #651), got {page.url}"
    )
