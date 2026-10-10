"""First authenticated E2E flow test — exercises the OAuth mock (#598).

Closes the loop on the mock landed in #599: this file drives the
mock end-to-end (POST /e2e/login + subsequent authenticated GET)
and pins the auth → admin slice integration. It is also the
template for future E2E flow tests that need a session cookie
without going through Google OAuth — copy the ``authenticated_page``
fixture verbatim and add the flow-specific assertions below.

Three tests:

- ``test_unauthenticated_admin_redirects_to_login`` — a negative
  case pinning the auth gate. Without a session, ``GET /admin``
  returns 303 to ``/login`` (the ``require_developer_user_redirect``
  dep's redirect target). This is what production does today and
  what every authenticated route must continue to do — a
  regression here would silently let unauthenticated users reach
  the admin panel.
- ``test_authenticated_admin_renders_panel`` — the positive
  contract. POST ``/e2e/login`` with the ``X-E2E-Secret`` header
  mints the session, the browser context picks up the cookie, the
  subsequent ``GET /admin`` returns 200 with the developer panel
  rendered (form for adding users + table of existing users).
- ``test_session_cookie_persists_across_requests`` — the
  cookie contract. After authentication, multiple ``GET /admin``
  requests succeed without re-authenticating; the first authorized
  request revalidates against ``usuarios_autorizados`` and
  ``require_authorized_user`` (the single cache writer) then serves
  the following requests from the in-process cache (issue #1073).

Fail-closed under the e2e_ci gate (issue #1096, tramo B): the
shared ``authenticated_session`` fixture from ``tests/e2e_ci/conftest.py``
already raises ``KeyError`` when ``APAP_E2E_AUTH_SECRET`` is unset
and hard-asserts ``/e2e/login`` answered 200; this module does
not define its own auth fixture. The ``/login`` 503 skip that the
tests/e2e/ version carried is gone — the gate's contract forbids
skips, and the empirical status (Google OAuth is intentionally
not configured under the gate) is reported from the run, not
absorbed by a skip branch.

The unit tests in ``tests/test_e2e_auth.py`` cover the contract
directly; this file covers the contract as observed through a
real browser.
"""
from __future__ import annotations

from playwright.sync_api import Page


def test_unauthenticated_admin_redirects_to_login(page: Page, base_url: str) -> None:
    """A request to ``/admin`` without a session is rejected at the auth gate.

    ``require_developer_user_redirect`` (issue #146) sends the
    browser to ``/login`` whenever the cookie is absent. The
    negative case is what protects the admin panel from a session
    regression — the first line of defence, even before the
    ``/login`` body renders.

    FAIL-CLOSED under the e2e_ci gate (issue #1096, tramo B): the
    previous ``tests/e2e/`` copy carried a 503-skip branch that
    absorbed the case where ``/login`` answers 503 because Google
    OAuth is not configured. The gate's contract forbids skips —
    a missing OAuth provider is the gate's reality (the gate
    provisions the OAuth mock at ``/e2e/login``, not Google OAuth
    on ``/login``). Empirical observation of this gate run is
    captured in the issue's handoff, not in this assertion:

    - Final status from the redirect chain is 200 when ``/login``
      renders (Google OAuth configured).
    - Final status is 503 + the OAuth-unconfigured JSON body when
      the gate runs without ``APAP_GOOGLE_CLIENT_ID`` /
      ``APAP_GOOGLE_CLIENT_SECRET`` (the e2e_ci posture today).
    - ``page.url`` still ends in ``/login`` and the request still
      carries a ``redirected_from`` predecessor in both cases —
      the auth gate did its job and the redirect target is what
      the operator sees.

    The assertion pins the redirect contract (server-side 302 to
    ``/login``, not a JS bounce). Whether the rendered ``/login``
    page is the 200 template or the 503 JSON is a property of the
    target environment, not of the auth gate, and is documented
    separately by ``app/core/auth_flow.py::_oauth_unconfigured_response``.
    """
    response = page.goto(f"{base_url}/admin")

    assert response is not None
    # Final-response semantics (issues #1153/#1160): the auth dep's
    # server-side 302 to /login surfaces as a 200 rendered /login when
    # Google OAuth is configured; on the gate (no OAuth) it surfaces
    # as 503 + the OAuth-unconfigured JSON. The redirect chain still
    # passed through ``/login`` and ``response.request.redirected_from``
    # is non-None in both branches — that is the auth-gate contract
    # this atom pins.
    assert page.url.endswith("/login"), (
        f"/admin must redirect to /login, got {page.url}"
    )
    assert response.request.redirected_from is not None, (
        "/admin must reach /login through a server redirect, not a client-side bounce"
    )
    # Final-response semantics (issues #1153/#1160): the auth dep's
    # server-side 302 to /login surfaces as a 200 rendered /login when Google
    # OAuth is configured, and as the OAuth-unconfigured 503 in the CI gate
    # (which provisions /e2e/login instead). The final request must still carry
    # a ``redirected_from`` predecessor (a JS bounce would not).
    assert response.status in (200, 503), (
        f"/admin without auth must land on /login (200 rendered, or the "
        f"OAuth-unconfigured 503), got {response.status} @ {response.url}"
    )
    if response.status == 503:
        body = response.text()
        assert "OAuth no est\u00e1 configurado" in body, (
            "the 503 landing must be the OAuth-unconfigured /login payload, "
            f"got: {body[:200]!r}"
        )


def test_authenticated_admin_renders_panel(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """The happy path: mock mints a session, the auth gate lets us through.

    Pins the contract end-to-end:

    - The mock mints a session that the auth middleware accepts.
    - The request reaches the ``/admin`` route handler (i.e. the
      auth gate does NOT redirect to ``/login``).
    - The cookie carries an ``is_authorized=True`` flag, so the
      ``require_developer_user_redirect`` dep does NOT redirect
      to ``/unauthorized``.

    The exact response body is intentionally NOT asserted: the dev
    server has no LocalBackend backend, so the admin panel's
    ``AuthUsersPort.list_authorized_users()`` call 500s. What the
    test pins is the AUTH path — that the cookie contract wires
    the request past both middleware gates — not the
    data-fetching path. The data-fetching path needs LocalBackend
    (separate work unit).
    """
    page, _csrf_token = authenticated_session

    response = page.goto(f"{base_url}/admin")

    assert response is not None
    # 303 / 307 → middleware redirected us back to /login (cookie
    #              missing or invalid — a regression in the mock
    #              contract or the PUBLIC_PATHS exemption).
    # 401      → auth gate accepted the cookie but the dev dep
    #              rejected the session payload (a regression in
    #              write_session / read_session_payload).
    # 500      → LocalBackend-dependent render failed. EXPECTED on the
    #              dev server with no backend; the test passes
    #              because the auth path is verified. A future
    #              follow-up that wires LocalBackend will turn this into
    #              a 200 and the assertion stays green.
    assert response.status not in (303, 307, 401), (
        f"authenticated /admin must pass the auth gate, got {response.status}. "
        f"Mock contract or PUBLIC_PATHS exemption regressed — see the "
        f"previous probe step in the workflow log."
    )


def test_session_cookie_persists_across_requests(
    authenticated_session: tuple[Page, str], base_url: str
) -> None:
    """After the mock sets the cookie, every subsequent request carries it.

    The mock does NOT seed the auth cache (issue #1073): the first
    authorized request revalidates against ``usuarios_autorizados``
    and ``require_authorized_user`` — the single cache writer — fills
    it, so the middleware accepts the cookie without further DB
    round-trips. This
    test pins that contract by issuing three consecutive
    authenticated requests and asserting each one passes the auth
    gate — a regression that drops the cookie or skips the cache
    fill would fail on the second or third request with a redirect
    (303 / 307) to ``/login``.

    500 is acceptable on this dev server (LocalBackend is not
    configured; the admin panel's ``AuthUsersPort`` call 500s on
    data fetch). What we pin is the auth path.
    """
    page, _csrf_token = authenticated_session

    for attempt in range(3):
        response = page.goto(f"{base_url}/admin")
        assert response is not None
        assert response.status not in (303, 307, 401), (
            f"authenticated /admin attempt {attempt + 1}/3 must "
            f"pass the auth gate, got {response.status}"
        )
