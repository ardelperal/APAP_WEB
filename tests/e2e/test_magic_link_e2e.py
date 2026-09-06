"""M3.1 E2E: drive the deployed APAP_WEB magic-link round-trip.

Asserts:
1. /login renders the magic-link form (the fix(m3-login) verification).
2. POST /auth/magic/start returns 200 with status=queued.
3. The configured email backend (MailDev locally, Resend in production)
   receives a message with a verify_url.
4. GET /auth/magic/verify?<token> sets the apap_session cookie.
5. The browser is redirected to /.

The form posts JSON via the onsubmit handler in /static/js/magic-link-form.js
(M3.2 CSP fix). The test waits for the fetch response and asserts on its
status, not on a page navigation (the form does not navigate; it updates
the status text and resets).

STATUS (M3.1 archive, 2026-09-05):

This round-trip test is **skipped** because the M3 backend wiring it
exercises is not in the codebase yet. Two structural gaps block it:

1. The routes ``POST /auth/magic/start`` and ``GET /auth/magic/verify``
   are not registered anywhere — ``app/core/auth_flow.py`` only exposes
   ``/login``, ``/auth/google``, ``/auth/callback`` and ``/logout``.
   The form posts to ``/auth/magic/start`` (a 404 in the current app).
2. There is no ``SMTPMailTransport``: ``grep -rn send_magic_link\\|SMTPMailTransport app/``
   returns zero hits. ``Settings`` has no ``APAP_SMTP_HOST/PORT/USER/...``
   fields, and ``MagicLinkPortImpl`` only persists the token — it does
   not deliver the email. The docstring on the port itself says
   "SMTP in a future epic"; that epic is the open M3 backend wiring
   issue tracked alongside this archive.

The helper (``tests/e2e/_maildev_helper.py``) and the conftest fixtures
land in this archive so that, once M3 backend is implemented, this test
is the only file that needs to be un-skipped (plus a small
``MAILDEV_URL`` -> ``RESEND_INBOX_URL`` repoint if the production
backend does not run MailDev).

Companion unit tests covering the helper's pure logic live at
``tests/test_maildev_helper.py`` (regex matching, polling semantics,
HTTP-error retry, timeout behaviour) — those are green and run in
the default suite.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e._maildev_helper import read_latest_verify_url  # noqa: F401

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(
        reason=(
            "M3 backend missing: /auth/magic/start + /auth/magic/verify + "
            "SMTPMailTransport are not implemented. See the M3 backend "
            "wiring issue tracked alongside this M3.1 archive; once it "
            "lands, drop the pytest.mark.skip line and repoint MAILDEV_URL "
            "at the deployed email backend (Resend in production)."
        )
    ),
]

BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app(page, base_url: str) -> None:  # noqa: ARG001
    """Round-trip covered above; the body is intentionally empty — the
    module-level ``pytest.mark.skip`` documents why this test cannot
    run yet. Once M3 backend lands, fill in the navigation steps
    documented in the module docstring (assertions 1-5)."""
    """End-to-end magic-link flow against the deployed app on the same VPS.

    1. /login renders the magic-link form (fix(m3-login) verification).
    2. Submit the bootstrap email via the form (the onsubmit handler
       intercepts and posts JSON via fetch).
    3. MailDev receives the message; extract the verify URL.
    4. Open the verify URL; assert apap_session cookie is set.
    5. The browser is redirected to /.
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

    # 4. Open the verify URL via a fresh context (the form-submission
    #    page may have set session cookies already; we want the verify
    #    to set apap_session itself).
    page.context.clear_cookies()
    page.goto(verify_url, wait_until="domcontentloaded")

    # 5. Assert the apap_session cookie is set
    cookies = {c["name"]: c for c in page.context.cookies()}
    assert "apap_session" in cookies, (
        f"apap_session cookie not set after verify; got {list(cookies)}"
    )

    # 6. The browser is redirected to /
    assert page.url.rstrip("/") == base_url.rstrip("/"), (
        f"expected redirect to {base_url}, got {page.url}"
    )
