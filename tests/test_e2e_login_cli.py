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

import httpx
import pytest

import scripts.e2e_login as e2e_login

SECRET_ENV = "APAP_TEST_E2E_SECRET"
SECRET = "e2e-unit-sentinel-secret"
SESSION_COOKIE = "apap_session"

SET_COOKIE = (
    "apap_session=signed-session-token-value; Path=/; HttpOnly; SameSite=strict; Max-Age=604800"
)


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
    assert cookie["domain"], "the cookie needs a domain for Playwright"
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
