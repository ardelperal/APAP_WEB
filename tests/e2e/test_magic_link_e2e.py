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

STATUS (M3.4 close-out, 2026-09-05):

The M3 backend wiring this test exercises now lands in the
``local_backend/app.py`` lifespan + ``local_backend/magic_link.py``
router. The round-trip is fully covered in-process by
``tests/integration/test_magic_link_routes.py`` (real Postgres via
``APAP_TEST_POSTGRES_DSN`` + fake SMTP transport), which pins the
same assertions 1-5 above via ``httpx.AsyncClient(ASGITransport)``.

The E2E remains ``pytest.mark.skip``'d here because it needs a
running ``apap-smtp-dev`` MailDev (the local email backend) and a
running ``apap.romancaba.com`` deployment. Both are operator-side
fixtures outside the unit-test boundary: MailDev's HTTP API is
currently broken (issue #649 follow-up), and the E2E runbook
lives at ``docs/runbooks/`` (to be authored as part of Phase 3,
#648). Once those land, this module drops the ``pytest.mark.skip``
line and the body below executes against the deployed app.

The unit tests for the helper (``tests/test_maildev_helper.py``) and
the SMTP transport (``tests/test_smtp_transport.py``) are green.
The round-trip coverage lives in the integration suite.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e._maildev_helper import read_latest_verify_url  # noqa: F401

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(
        reason=(
            "Round-trip covered in-process by "
            "tests/integration/test_magic_link_routes.py. The E2E path "
            "needs a live apap-smtp-dev MailDev container (currently "
            "broken — issue #649 follow-up) and a running production "
            "deploy; see Phase 3 (#648) runbook for the operator "
            "checklist."
        )
    ),
]

BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app(page, base_url: str) -> None:  # noqa: ARG001
    """Round-trip covered by the integration suite; once MailDev + the
    deployed-app E2E runbook (Phase 3) are green, fill in the
    navigation steps documented in the module docstring (assertions
    1-5) and drop the ``pytest.mark.skip`` above."""
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
