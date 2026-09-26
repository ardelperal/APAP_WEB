"""E2E: the e2e_login storageState authenticates a ``new_context`` (issue #906).

Two layers of proof that the storageState minted by
``scripts/e2e_login.py`` is Playwright-compatible:

- ``test_generated_storage_state_loads_into_new_context`` builds the
  state file against a mocked transport (no live server needed) and
  loads it into a real Chromium context, pinning the cookie shape
  Playwright accepts.
- ``test_secure_set_cookie_against_http_origin_loads_into_new_context``
  pins fix F2 (issue #906): a Secure Set-Cookie minted against an http
  origin must still land in Chromium (secure derived from the scheme).
- ``test_minted_state_authenticates_requests_against_live_server``
  consumes the shared ``authenticated_state`` fixture (the same path
  every migrated suite takes) and asserts an authenticated ``GET
  /admin`` — 303-redirect without a session, 200 with one.

Both tests auto-skip with the rest of ``tests/e2e/`` when chromium is
missing or ``APAP_E2E_SKIP=1`` is set (parent conftest).
"""

from __future__ import annotations

import httpx
from playwright.sync_api import Browser

import scripts.e2e_login as e2e_login

SECRET_ENV = "APAP_E2E_AUTH_SECRET"


def test_generated_storage_state_loads_into_new_context(
    tmp_path, monkeypatch, _browser: Browser
) -> None:
    """A minted storageState file loads into Chromium with the session cookie."""
    secret = "storage-state-shape-sentinel"
    monkeypatch.setenv(SECRET_ENV, secret)
    set_cookie = "apap_session=tok; Path=/; HttpOnly; SameSite=strict; Max-Age=604800"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers=[("Set-Cookie", set_cookie)], json={"authenticated": True}
        )
    )
    out = tmp_path / "state.json"
    e2e_login.mint_storage_state(
        base_url="http://127.0.0.1:9000",
        secret_env=SECRET_ENV,
        email=None,
        out_path=out,
        transport=transport,
    )

    context = _browser.new_context(storage_state=str(out))
    try:
        (cookie,) = [
            c for c in context.cookies("http://127.0.0.1:9000/") if c["name"] == "apap_session"
        ]
        assert cookie["value"] == "tok"
        assert cookie["httpOnly"] is True
        assert secret not in out.read_text(encoding="utf-8"), (
            "the storageState carries session cookies only, never the secret"
        )
    finally:
        context.close()


def test_secure_set_cookie_against_http_origin_loads_into_new_context(
    tmp_path, monkeypatch, _browser: Browser
) -> None:
    """F2/F6 end-to-end: a Secure Set-Cookie minted against http:// survives.

    The server sets ``secure=not settings.debug``; copying that flag
    verbatim onto a plain-http origin makes Chromium silently drop the
    cookie (``context.cookies() == []``) while the CLI exits 0. The
    minted storageState must derive ``secure`` from the --base-url
    scheme, so the cookie is present and not marked Secure.
    """
    secret = "storage-state-shape-sentinel"
    monkeypatch.setenv(SECRET_ENV, secret)
    set_cookie = "apap_session=tok; Path=/; HttpOnly; SameSite=strict; Max-Age=604800; Secure"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers=[("Set-Cookie", set_cookie)], json={"authenticated": True}
        )
    )
    out = tmp_path / "state.json"
    e2e_login.mint_storage_state(
        base_url="http://127.0.0.1:9000",
        secret_env=SECRET_ENV,
        email=None,
        out_path=out,
        transport=transport,
    )

    context = _browser.new_context(storage_state=str(out))
    try:
        (cookie,) = [
            c for c in context.cookies("http://127.0.0.1:9000/") if c["name"] == "apap_session"
        ]
        assert cookie["value"] == "tok", "the cookie must survive into Chromium"
        assert cookie["secure"] is False, (
            "secure must derive from the http base-url scheme, not the "
            "server's Secure flag"
        )
    finally:
        context.close()


def test_minted_state_authenticates_requests_against_live_server(
    _browser: Browser, authenticated_state, base_url: str
) -> None:
    """A context built from the shared fixture state reaches /admin (200)."""
    context = _browser.new_context(storage_state=str(authenticated_state), base_url=base_url)
    try:
        response = context.request.get(f"{base_url}/admin")
        assert response.status == 200, (
            "a context authenticated via the storageState must reach /admin, "
            f"got {response.status} (303 would mean the cookie was not applied)"
        )
    finally:
        context.close()
