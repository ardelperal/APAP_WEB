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

Operator-side fixture contract:

- ``APAP_E2E_BASE_URL`` (defaults to ``http://127.0.0.1:8000``): the URL the
  deployed app is reachable at. For production runs against
  ``https://apap.romancaba.com`` set this env var explicitly.
- ``E2E_BOOTSTRAP_EMAIL`` (defaults to ``ardelperal@gmail.com``): the email
  the form sends the magic-link to.
- ``MAILDEV_URL`` (defaults to ``http://apap-smtp-dev:8025``): the MailDev
  HTTP API the helper polls. Local docker-compose deploys run MailDev next
  to ``apap-web`` under that host.

Skip contract:

The test requires ``APAP_E2E_BASE_URL`` and ``MAILDEV_URL`` to be set AND
``MAILDEV_URL`` to answer the MailDev HTTP API (``/api/v2/messages``). When
those are missing or unreachable, the test skips with a clear message that
points at the operator-side runbook (Phase 3, issue #648). The round-trip
contract also lives in ``tests/integration/test_magic_link_routes.py``
(real Postgres via ``APAP_TEST_POSTGRES_DSN`` + fake SMTP transport), which
pins the same assertions 1-5 via ``httpx.AsyncClient(ASGITransport)`` and
runs without the operator-side fixtures.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

from tests.e2e._maildev_helper import read_latest_verify_url  # noqa: F401

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("APAP_E2E_BASE_URL") is None
        and os.environ.get("MAILDEV_URL") is None
        and os.environ.get("APAP_E2E_REQUIRE_ROUND_TRIP") != "1",
        reason=(
            "E2E round-trip requires APAP_E2E_BASE_URL + a reachable "
            "MailDev at MAILDEV_URL. Set both env vars to enable, or "
            "set APAP_E2E_REQUIRE_ROUND_TRIP=1 to fail loud instead of "
            "skipping. Round-trip is covered in-process by "
            "tests/integration/test_magic_link_routes.py; see Phase 3 "
            "(issue #648) operator runbook for the deployed-app check."
        ),
    ),
]


def _maildev_reachable(url: str) -> bool:
    """Return True when the MailDev HTTP API answers the version probe.

    Probes ``{url}/api/v2/messages`` with a short timeout. Any HTTPError,
    URLError or TimeoutError is treated as "not reachable" and yields False;
    the test then fails loud instead of silently skipping.
    """
    probe = url.rstrip("/") + "/api/v2/messages"
    try:
        with urllib.request.urlopen(probe, timeout=5) as response:  # noqa: S310
            return 200 <= response.status < 300
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False


BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")
BASE_URL = os.environ.get("APAP_E2E_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(autouse=True)
def _require_maildev_reachable() -> None:
    """Fail loud when the operator enabled the test but the env is incomplete.

    The skipif above allows local runs without env vars; this fixture fires
    when the operator opts in (MAILDEV_URL or APAP_E2E_BASE_URL set) so that
    a misconfigured deploy does not silently pass.
    """
    opted_in = any(
        var in os.environ
        for var in ("MAILDEV_URL", "APAP_E2E_BASE_URL", "APAP_E2E_REQUIRE_ROUND_TRIP")
    )
    if not opted_in:
        return
    if not _maildev_reachable(MAILDEV_URL):
        pytest.fail(
            f"MailDev HTTP API not reachable at {MAILDEV_URL}/api/v2/messages. "
            f"Either start the apap-smtp-dev container or unset MAILDEV_URL "
            f"to fall back to the integration coverage. See docs/runbooks/ "
            f"and Phase 3 (issue #648)."
        )


def test_magic_link_round_trip_against_deployed_app(page, base_url: str) -> None:
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
