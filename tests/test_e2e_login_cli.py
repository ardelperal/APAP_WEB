"""Unit tests for the E2E login CLI (issue #906).

The CLI (``scripts/e2e_login.py``) mints a Playwright ``storageState``
file by calling the test-only ``GET /e2e/login`` mock with the
``X-E2E-Secret`` header. These tests pin the CLI contract:

- happy path: the response's session cookie is captured into a
  Playwright-compatible storageState written with ``0600`` permissions;
- a missing secret environment variable fails with an error that names
  the variable, never a value;
- a rejected login (401) and a cookie-less 200 both fail with clear
  errors;
- no failure path ever echoes the secret value (stderr is asserted
  against the sentinel secret).

Classification (docs/quality/test-audit.md discipline): unit service —
the CLI orchestrates an HTTP call whose handler is replaced by
``httpx.MockTransport`` injected through the ``transport`` seam. No SQL,
no DB triggers, no CTE rollback: Gate B does not apply, so no
integration sibling is required.
"""

from __future__ import annotations

import json
import stat
import time
from email.utils import parsedate_to_datetime

import httpx
import pytest

import scripts.e2e_login as e2e_login

SECRET_ENV = "APAP_TEST_E2E_SECRET"
SECRET = "e2e-unit-sentinel-secret"
SESSION_COOKIE = "apap_session"

SET_COOKIE = (
    "apap_session=signed-session-token-value; Path=/; HttpOnly; SameSite=strict; Max-Age=604800"
)
SET_COOKIE_SECURE = SET_COOKIE + "; Secure"
EXPIRES_HTTP_DATE = "Wed, 21 Oct 2026 07:28:00 GMT"


def _mint_transport(handler) -> httpx.MockTransport:
    """Build a transport that also pins the request contract."""

    def _assert_contract(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/e2e/login", (
            f"the CLI must call /e2e/login, got {request.url.path}"
        )
        assert request.method == "GET"
        assert request.headers.get("X-E2E-Secret") == SECRET, (
            "the CLI must send the secret via the X-E2E-Secret header"
        )
        return handler(request)

    return httpx.MockTransport(_assert_contract)


def _happy_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers=[("Set-Cookie", SET_COOKIE)],
        json={"authenticated": True, "email": "e2e@apap.local"},
    )


def test_mint_writes_playwright_storage_state_with_0600(tmp_path, monkeypatch) -> None:
    """Happy path: session cookie captured into a 0600 storageState file."""
    monkeypatch.setenv(SECRET_ENV, SECRET)
    out = tmp_path / "nested" / "state.json"
    state = e2e_login.mint_storage_state(
        base_url="http://127.0.0.1:8000",
        secret_env=SECRET_ENV,
        email="e2e@apap.local",
        out_path=out,
        transport=_mint_transport(_happy_handler),
    )

    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600, f"storageState must be 0600, got {oct(mode)}"
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk == state

    assert on_disk["origins"] == []
    (cookie,) = on_disk["cookies"]
    assert cookie["name"] == SESSION_COOKIE
    assert cookie["value"] == "signed-session-token-value"
    assert cookie["path"] == "/"
    assert cookie["httpOnly"] is True
    assert cookie["sameSite"] == "Strict"
    assert cookie["domain"] == "127.0.0.1", (
        "a host-only cookie (no Domain attribute) must be scoped to the "
        "request host, not just any truthy value"
    )
    # Max-Age=604800 must survive into the storageState: a browser-session
    # cookie (-1) would silently drop the server's 7-day lifetime.
    expected_floor = int(time.time()) + 604800 - 5
    expected_ceiling = int(time.time()) + 604800 + 5
    assert expected_floor <= cookie["expires"] <= expected_ceiling, (
        f"expires must reflect Max-Age=604800, got {cookie['expires']}"
    )
    assert SECRET not in json.dumps(on_disk), (
        "only session cookies belong in the storageState, never the secret"
    )


def test_missing_secret_env_error_names_variable(tmp_path, monkeypatch) -> None:
    """Missing secret env fails clearly, naming the variable, not a value."""
    monkeypatch.delenv(SECRET_ENV, raising=False)
    with pytest.raises(e2e_login.MissingSecretError, match=SECRET_ENV):
        e2e_login.mint_storage_state(
            base_url="http://127.0.0.1:8000",
            secret_env=SECRET_ENV,
            email=None,
            out_path=tmp_path / "state.json",
        )


def test_main_reports_missing_secret_without_echoing_value(tmp_path, monkeypatch, capsys) -> None:
    """main() exits non-zero with a clear stderr error for a missing secret."""
    monkeypatch.delenv(SECRET_ENV, raising=False)
    exit_code = e2e_login.main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--secret-env",
            SECRET_ENV,
            "--out",
            str(tmp_path / "state.json"),
        ]
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    assert SECRET_ENV in captured.err, "the error must name the env var"
    assert captured.out == ""
    assert not (tmp_path / "state.json").exists()


def test_rejected_login_fails_without_echoing_secret(tmp_path, monkeypatch, capsys) -> None:
    """A 401 from /e2e/login fails clearly; stderr never contains the secret."""
    monkeypatch.setenv(SECRET_ENV, SECRET)

    def _rejecting_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "X-E2E-Secret missing or invalid."})

    exit_code = e2e_login.main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--secret-env",
            SECRET_ENV,
            "--email",
            "e2e@apap.local",
            "--out",
            str(tmp_path / "state.json"),
        ],
        transport=_mint_transport(_rejecting_handler),
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "401" in captured.err, "the error must state the HTTP status"
    assert SECRET not in captured.err, "the secret value must never be echoed"
    assert SECRET not in captured.out
    assert not (tmp_path / "state.json").exists()


def test_cookieless_success_fails_with_clear_error(tmp_path, monkeypatch) -> None:
    """A 200 without the session cookie must fail with a clear error."""
    monkeypatch.setenv(SECRET_ENV, SECRET)

    def _cookieless_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"authenticated": False})

    with pytest.raises(e2e_login.SessionCookieError, match=SESSION_COOKIE):
        e2e_login.mint_storage_state(
            base_url="http://127.0.0.1:8000",
            secret_env=SECRET_ENV,
            email=None,
            out_path=tmp_path / "state.json",
            transport=_mint_transport(_cookieless_handler),
        )
    assert not (tmp_path / "state.json").exists()


def test_rejected_login_error_carries_status_code(tmp_path, monkeypatch) -> None:
    """LoginFailedError carries the HTTP status so the fixture skip policy (F1)
    can tell a benign 404 (mock disabled) from a fatal 401 (wrong secret)."""
    monkeypatch.setenv(SECRET_ENV, SECRET)

    def _rejecting_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid"})

    with pytest.raises(e2e_login.LoginFailedError) as excinfo:
        e2e_login.mint_storage_state(
            base_url="http://127.0.0.1:8000",
            secret_env=SECRET_ENV,
            email=None,
            out_path=tmp_path / "state.json",
            transport=_mint_transport(_rejecting_handler),
        )
    assert excinfo.value.status_code == 401


@pytest.mark.parametrize(
    ("base_url", "set_cookie", "expected_secure"),
    [
        ("http://127.0.0.1:8000", SET_COOKIE_SECURE, False),
        ("https://apap.example.test", SET_COOKIE, True),
    ],
    ids=["http-plus-secure-cookie", "https-plain-cookie"],
)
def test_minted_cookie_secure_derives_from_base_url_scheme(
    tmp_path,
    monkeypatch,
    base_url: str,
    set_cookie: str,
    expected_secure: bool,
) -> None:
    """The storageState cookie's secure flag follows --base-url's scheme (F2).

    Copying the server's Secure flag verbatim onto a plain-http origin
    makes Chromium silently drop the cookie (judge-reproduced:
    ``context.cookies() == []`` while the CLI exits 0), so the scheme of
    the URL the browser will replay the cookie against decides.
    """
    monkeypatch.setenv(SECRET_ENV, SECRET)
    state = e2e_login.mint_storage_state(
        base_url=base_url,
        secret_env=SECRET_ENV,
        email=None,
        out_path=tmp_path / "state.json",
        transport=_mint_transport(
            lambda request: httpx.Response(
                200, headers=[("Set-Cookie", set_cookie)], json={"authenticated": True}
            )
        ),
    )
    (cookie,) = state["cookies"]
    assert cookie["secure"] is expected_secure, (
        f"secure must derive from the {base_url.split(':')[0]} scheme"
    )


def test_parse_expires_prefers_max_age_over_expires() -> None:
    """RFC 6265 section 5.2.2: a valid Max-Age wins when both are present (F4)."""
    expected_floor = int(time.time()) + 3600 - 5
    expected_ceiling = int(time.time()) + 3600 + 5
    result = e2e_login._parse_expires(EXPIRES_HTTP_DATE, "3600")
    assert expected_floor <= result <= expected_ceiling, (
        "with both attributes present, Max-Age=3600 must decide, not Expires"
    )


def test_parse_expires_uses_expires_when_max_age_absent() -> None:
    """JD-B-006: the Expires-only branch resolves to the HTTP-date's epoch."""
    expected = int(parsedate_to_datetime(EXPIRES_HTTP_DATE).timestamp())
    assert e2e_login._parse_expires(EXPIRES_HTTP_DATE, "") == expected


def test_parse_expires_invalid_values_degrade_to_session_cookie() -> None:
    """Edge paths: unparseable values and negative Max-Age degrade to -1."""
    assert e2e_login._parse_expires("not-a-date", "not-a-number") == -1
    assert e2e_login._parse_expires("", "") == -1
    assert e2e_login._parse_expires("", "-5") == -1
    assert e2e_login._parse_expires(EXPIRES_HTTP_DATE, "-5") == int(
        parsedate_to_datetime(EXPIRES_HTTP_DATE).timestamp()
    )


def _counting_transport(counter: list[int]) -> httpx.MockTransport:
    """A transport that counts mints and answers with a happy 200."""

    def _handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(
            200, headers=[("Set-Cookie", SET_COOKIE)], json={"authenticated": True}
        )

    return httpx.MockTransport(_handler)


def test_auth_state_cache_does_not_re_mint_before_ttl_threshold(
    tmp_path, monkeypatch
) -> None:
    """F3: a cached mint younger than the 240s TTL is reused, not re-minted."""
    monkeypatch.setenv(SECRET_ENV, SECRET)
    counter: list[int] = []
    now = 1_000.0
    cache = e2e_login.AuthStateCache(
        base_url="http://127.0.0.1:8000",
        secret_env=SECRET_ENV,
        out_path=tmp_path / "state.json",
        transport=_counting_transport(counter),
        clock=lambda: now,
    )

    first = cache.ensure_fresh()
    assert first == tmp_path / "state.json"
    assert json.loads(first.read_text(encoding="utf-8"))["origins"] == []
    assert len(counter) == 1

    now += e2e_login.AUTH_STATE_REFRESH_TTL_SECONDS - 1  # 1s under the threshold
    assert cache.ensure_fresh() == first
    assert len(counter) == 1, "a mint inside the TTL window must be reused"


def test_auth_state_cache_re_mints_after_ttl_threshold(tmp_path, monkeypatch) -> None:
    """F3: once the cached mint reaches the 240s threshold, ensure_fresh re-mints."""
    monkeypatch.setenv(SECRET_ENV, SECRET)
    counter: list[int] = []
    now = 1_000.0
    cache = e2e_login.AuthStateCache(
        base_url="http://127.0.0.1:8000",
        secret_env=SECRET_ENV,
        out_path=tmp_path / "state.json",
        transport=_counting_transport(counter),
        clock=lambda: now,
    )

    first = cache.ensure_fresh()
    assert len(counter) == 1

    now += e2e_login.AUTH_STATE_REFRESH_TTL_SECONDS  # exactly at the threshold
    second = cache.ensure_fresh()
    assert second == first, "the path stays stable; the file is rewritten in place"
    assert len(counter) == 2, "a mint at/after the TTL threshold must re-mint"
    assert json.loads(second.read_text(encoding="utf-8"))["origins"] == []


def test_authenticated_state_skip_policy_skips_only_benign_failures() -> None:
    """F1: the fixture skip policy skips ONLY the secret-missing and 404 cases.

    A 401 (wrong/stale secret), a 503 (empty server secret), and transport
    errors must be classified fatal so the authenticated suite FAILS
    loudly instead of green-skipping. The classifier lives in
    ``scripts.e2e_login`` (not the e2e conftest) so importing it never
    triggers the e2e package's module-level environment setup.
    """
    missing_secret = e2e_login.MissingSecretError("environment variable 'X' is not set")
    assert e2e_login.is_benign_login_failure(missing_secret) is True

    mock_disabled = e2e_login.LoginFailedError("/e2e/login returned 404", status_code=404)
    assert e2e_login.is_benign_login_failure(mock_disabled) is True

    wrong_secret = e2e_login.LoginFailedError("/e2e/login returned 401", status_code=401)
    assert e2e_login.is_benign_login_failure(wrong_secret) is False, (
        "a wrong/stale secret with the env var present must FAIL, not skip"
    )
    empty_server_secret = e2e_login.LoginFailedError(
        "/e2e/login returned 503", status_code=503
    )
    assert e2e_login.is_benign_login_failure(empty_server_secret) is False
    transport_failure = httpx.ConnectError("connection refused")
    assert e2e_login.is_benign_login_failure(transport_failure) is False


@pytest.mark.parametrize(
    "transport_error",
    [httpx.ConnectError("Connection refused"), OSError("Network is unreachable")],
    ids=["httpx-connect-error", "os-error"],
)
def test_main_transport_error_exits_1_with_stderr_message(
    tmp_path, monkeypatch, capsys, transport_error
) -> None:
    """F5: transport failures honor the documented exit-1-with-stderr contract.

    No raw traceback may escape main(), and the diagnostic must never
    echo the secret value.
    """
    monkeypatch.setenv(SECRET_ENV, SECRET)

    def _unreachable(request: httpx.Request) -> httpx.Response:
        raise transport_error

    exit_code = e2e_login.main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--secret-env",
            SECRET_ENV,
            "--out",
            str(tmp_path / "state.json"),
        ],
        transport=httpx.MockTransport(_unreachable),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("e2e_login:"), (
        "the diagnostic must go to stderr prefixed with e2e_login:, not a traceback"
    )
    assert SECRET not in captured.err, "the secret value must never be echoed"
    assert SECRET not in captured.out
    assert not (tmp_path / "state.json").exists()


def test_main_success_prints_report_without_secret(tmp_path, monkeypatch, capsys) -> None:
    """main() succeeds, writes the file, and never prints the secret."""
    monkeypatch.setenv(SECRET_ENV, SECRET)
    out = tmp_path / "state.json"
    exit_code = e2e_login.main(
        [
            "--base-url",
            "http://127.0.0.1:8000",
            "--secret-env",
            SECRET_ENV,
            "--email",
            "e2e@apap.local",
            "--out",
            str(out),
        ],
        transport=_mint_transport(_happy_handler),
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert str(out) in captured.out
    assert SECRET not in captured.out + captured.err
