"""Behaviour tests for scripts/production_smoke.py (issue #1131).

The smoke is unauthenticated and secretless: it proves the deployed revision is
live and that the public and protected surfaces answer sanely. HTTP is stubbed
through the ``fetch`` seam; no test touches the network.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import production_smoke as ps  # noqa: E402

SHA = "a" * 40
BASE = "https://apap.example.test"
HEALTH_URL = f"{BASE}/healthz"


def _healthy(revision: str = SHA) -> ps.Response:
    body = json.dumps({"status": "ok", "revision": revision}).encode()
    return ps.Response(status=200, location=None, body=body)


def _login_page() -> ps.Response:
    return ps.Response(status=200, location=None, body=b"<html>login</html>")


def _redirect(location: str = "/login?next=%2F", status: int = 302) -> ps.Response:
    return ps.Response(status=status, location=location, body=b"")


def _site(**routes: ps.Response | Exception) -> Callable[[str], ps.Response]:
    """Build a fetch stub keyed by path (keyword names use ``_`` for ``/``)."""
    table = {"/" + key.strip("_").replace("__", "/"): value for key, value in routes.items()}

    def fetch(url: str) -> ps.Response:
        path = url.removeprefix(BASE)
        outcome = table[path]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fetch


def _good_site() -> Callable[[str], ps.Response]:
    return _site(healthz=_healthy(), login=_login_page(), _=_redirect())


def _no_sleep(_seconds: float) -> None:
    return None


def _retry(
    attempts: int = 1, interval: float = 0, sleep: Callable[[float], None] = _no_sleep
) -> ps.Retry:
    return ps.Retry(attempts=attempts, interval=interval, sleep=sleep)


FOUR_ATTEMPTS = 4
THREE_ATTEMPTS = 3
USAGE_ERROR = 2


def test_origin_strips_the_path_of_the_health_url() -> None:
    assert ps.origin("https://apap.example.test/healthz") == "https://apap.example.test"
    assert ps.origin("http://localhost:8000/healthz") == "http://localhost:8000"


@pytest.mark.parametrize("url", ["", "ftp://x/healthz", "apap.example.test/healthz", "https://"])
def test_origin_rejects_non_http_urls(url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        ps.origin(url)


def test_run_smoke_passes_when_every_check_holds() -> None:
    results = ps.run_smoke(_good_site(), BASE, SHA, _retry())

    assert [r.ok for r in results] == [True, True, True]
    assert {r.name for r in results} == {"revision", "public /login", "protected / redirect"}


def test_revision_check_retries_until_the_new_revision_is_live() -> None:
    answers = [_healthy("b" * 40), _healthy("b" * 40), _healthy(SHA)]
    sleeps: list[float] = []

    def fetch(_url: str) -> ps.Response:
        return answers.pop(0)

    result = ps.check_revision(fetch, BASE, SHA, _retry(5, 7, sleeps.append))

    assert result.ok
    assert sleeps == [7, 7]


def test_revision_check_fails_when_the_wrong_revision_stays_live() -> None:
    fetch = _site(healthz=_healthy("b" * 40))

    result = ps.check_revision(fetch, BASE, SHA, _retry(3, 1))

    assert not result.ok
    assert SHA in result.detail
    assert "b" * 40 in result.detail


def test_revision_check_is_bounded_by_the_attempt_count() -> None:
    calls: list[str] = []

    def fetch(url: str) -> ps.Response:
        calls.append(url)
        return ps.Response(status=503, location=None, body=b"")

    result = ps.check_revision(fetch, BASE, SHA, _retry(4, 0))

    assert not result.ok
    assert len(calls) == FOUR_ATTEMPTS
    assert "503" in result.detail


def test_revision_check_survives_transport_errors_then_fails() -> None:
    fetch = _site(healthz=ps.FetchError("connection refused"))

    result = ps.check_revision(fetch, BASE, SHA, _retry(2, 0))

    assert not result.ok
    assert "connection refused" in result.detail


def test_revision_check_rejects_a_non_json_or_unhealthy_body() -> None:
    fetch = _site(healthz=ps.Response(status=200, location=None, body=b"<html>"))
    assert not ps.check_revision(fetch, BASE, SHA, _retry(1, 0)).ok

    bad = json.dumps({"status": "degraded", "revision": SHA}).encode()
    fetch = _site(healthz=ps.Response(status=200, location=None, body=bad))
    assert not ps.check_revision(fetch, BASE, SHA, _retry(1, 0)).ok


def test_public_route_must_answer_200() -> None:
    fetch = _site(login=ps.Response(status=500, location=None, body=b""))

    result = ps.check_public(fetch, BASE, "/login", _retry())

    assert not result.ok
    assert "500" in result.detail


def test_public_route_transport_error_fails_the_check() -> None:
    result = ps.check_public(_site(login=ps.FetchError("timed out")), BASE, "/login", _retry())

    assert not result.ok
    assert "timed out" in result.detail


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_protected_route_accepts_any_redirect_to_login(status: int) -> None:
    result = ps.check_protected(_site(_=_redirect("/login", status)), BASE, "/", _retry())

    assert result.ok


def test_protected_route_accepts_an_absolute_login_location() -> None:
    result = ps.check_protected(_site(_=_redirect(f"{BASE}/login?next=/")), BASE, "/", _retry())

    assert result.ok


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.test/login",
        "//evil.example.test/login",
        "http://apap.example.test/login",
    ],
)
def test_protected_route_rejects_a_login_redirect_to_another_origin(location: str) -> None:
    result = ps.check_protected(_site(_=_redirect(location)), BASE, "/", _retry())

    assert not result.ok
    assert location in result.detail


def test_public_route_retries_a_transient_failure_then_passes() -> None:
    answers = [ps.Response(403, None, b""), _login_page()]
    sleeps: list[float] = []

    def fetch(_url: str) -> ps.Response:
        return answers.pop(0)

    result = ps.check_public(fetch, BASE, "/login", _retry(3, 5, sleeps.append))

    assert result.ok
    assert sleeps == [5]


def test_public_route_fails_after_the_retry_budget() -> None:
    calls: list[str] = []

    def fetch(url: str) -> ps.Response:
        calls.append(url)
        return ps.Response(503, None, b"")

    result = ps.check_public(fetch, BASE, "/login", _retry(3, 0))

    assert not result.ok
    assert len(calls) == THREE_ATTEMPTS
    assert "503" in result.detail


def test_protected_route_retries_a_transient_failure_then_passes() -> None:
    answers: list[ps.Response | Exception] = [ps.FetchError("reset"), _redirect()]

    def fetch(_url: str) -> ps.Response:
        outcome = answers.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert ps.check_protected(fetch, BASE, "/", _retry(2, 0)).ok


def test_protected_route_fails_after_the_retry_budget() -> None:
    calls: list[str] = []

    def fetch(url: str) -> ps.Response:
        calls.append(url)
        return ps.Response(502, None, b"")

    result = ps.check_protected(fetch, BASE, "/", _retry(3, 0))

    assert not result.ok
    assert len(calls) == THREE_ATTEMPTS
    assert "502" in result.detail


@pytest.mark.parametrize("status", [500, 502, 503])
def test_protected_route_5xx_fails(status: int) -> None:
    result = ps.check_protected(_site(_=ps.Response(status, None, b"")), BASE, "/", _retry())

    assert not result.ok
    assert str(status) in result.detail


def test_protected_route_without_a_redirect_fails() -> None:
    result = ps.check_protected(_site(_=_login_page()), BASE, "/", _retry())

    assert not result.ok
    assert "200" in result.detail


def test_protected_route_redirecting_elsewhere_fails() -> None:
    result = ps.check_protected(_site(_=_redirect("/unauthorized")), BASE, "/", _retry())

    assert not result.ok
    assert "/unauthorized" in result.detail


def test_protected_route_redirect_without_location_fails() -> None:
    result = ps.check_protected(_site(_=ps.Response(302, None, b"")), BASE, "/", _retry())

    assert not result.ok


def test_main_exit_zero_and_prints_each_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ps, "fetch_url", _good_site())

    code = ps.main(["--health-url", HEALTH_URL, "--revision", SHA, "--attempts", "1"])

    assert code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower()
    assert "revision" in out


def test_main_exit_one_when_a_check_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        ps, "fetch_url", _site(healthz=_healthy(), login=_login_page(), _=_login_page())
    )

    code = ps.main(["--health-url", HEALTH_URL, "--revision", SHA, "--attempts", "1"])

    assert code == 1
    assert "::error::" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--health-url", HEALTH_URL],
        ["--revision", SHA],
        ["--health-url", "not-a-url", "--revision", SHA],
        ["--health-url", HEALTH_URL, "--revision", SHA, "--attempts", "0"],
        ["--health-url", HEALTH_URL, "--revision", SHA, "--interval", "-1"],
    ],
)
def test_main_usage_errors_exit_two(argv: list[str]) -> None:
    assert ps.main(argv) == USAGE_ERROR


def test_fetch_url_refuses_non_http_schemes() -> None:
    with pytest.raises(ps.FetchError, match="scheme"):
        ps.fetch_url("file:///etc/passwd")


def test_fetch_url_sends_the_smoke_user_agent_on_every_request() -> None:
    seen: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            seen.append(self.headers.get("User-Agent"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        ps.fetch_url(f"{base}/healthz")
        ps.fetch_url(f"{base}/login")
    finally:
        server.shutdown()
        server.server_close()

    assert seen == [ps.USER_AGENT, ps.USER_AGENT]
    assert ps.USER_AGENT.startswith("apap-production-smoke/")
    assert not any(agent and agent.startswith("Python-urllib") for agent in seen)
