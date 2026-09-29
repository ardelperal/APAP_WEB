"""Unauthenticated production smoke for a freshly deployed revision (issue #1131).

The smoke holds no secret and logs nobody in. After ``deploy`` succeeds the
``production-smoke`` job of ``deploy.yml`` runs it against the public origin and
records the result as the commit status ``release/smoke-production``.

Checks, all over plain HTTP (stdlib only, redirects are never followed):

    revision            ``/healthz`` reports ``status: ok`` and the expected SHA
                        (bounded retries: the deploy finishes just before)
    public /login       the login page answers 200 (same bounded retries)
    protected / redirect  an unauthenticated ``/`` redirects to ``/login`` on
                        the same origin and never answers 5xx (same retries)

Every request carries ``USER_AGENT``: the edge in front of production rejects
the default ``Python-urllib`` agent with HTTP 403 (issue #1134).

This is NOT the authenticated e2e battery: it proves the revision is live and
the auth gate is up, nothing about authenticated behaviour (see
``docs/runbooks/e2e-production.md``).

Usage::

    python scripts/production_smoke.py --health-url https://HOST/healthz --revision SHA

The origin is derived from ``--health-url`` (the repository variable
``APAP_DEPLOY_HEALTH_URL``); no host is hardcoded.

Exit codes:
    0 - every check passed
    1 - at least one check failed
    2 - usage error

Tests: ``tests/test_production_smoke.py`` (HTTP stubbed, no network).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

EXIT_OK = 0
HTTP_OK = 200
EXIT_FAILED = 1
EXIT_USAGE_ERROR = 2
LOGIN_PATH = "/login"
PROTECTED_PATH = "/"
REQUEST_TIMEOUT_SECONDS = 15.0
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
SERVER_ERROR_FLOOR = 500
USER_AGENT = "apap-production-smoke/1 (+https://github.com/ardelperal/APAP_WEB)"


class FetchError(Exception):
    """A transport failure (DNS, connection, TLS, timeout, disallowed scheme)."""


@dataclass(frozen=True)
class Response:
    """The parts of an HTTP response the smoke inspects."""

    status: int
    location: str | None
    body: bytes


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one smoke check."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Retry:
    """Bounded retry policy shared by every check.

    Worst case with the CLI defaults (6 attempts, 10 s interval, 15 s request
    timeout) is 3 checks x (6 x 15 s + 5 x 10 s) = 420 s (7 min), inside the
    ``timeout-minutes: 10`` of the ``production-smoke`` job in ``deploy.yml``.
    Raising ``--attempts`` or ``--interval`` there must keep that bound.
    """

    attempts: int
    interval: float
    sleep: Callable[[float], None] = time.sleep


Fetch = Callable[[str], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx answers instead of following them."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def fetch_url(url: str) -> Response:
    """GET ``url`` without following redirects; HTTP error statuses are responses."""
    if urlsplit(url).scheme not in {"http", "https"}:
        message = f"unsupported URL scheme in {url!r}"
        raise FetchError(message)
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, headers={"User-Agent": USER_AGENT}, method="GET"
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as reply:  # noqa: S310
            return Response(reply.status, reply.headers.get("Location"), reply.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, error.headers.get("Location"), error.read())
    except (urllib.error.URLError, OSError) as error:
        raise FetchError(str(error)) from error


def origin(health_url: str) -> str:
    """Return ``scheme://host[:port]`` of ``health_url`` or raise ``ValueError``."""
    parts = urlsplit(health_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        message = f"expected an http(s) URL with a host, got {health_url!r}"
        raise ValueError(message)
    return f"{parts.scheme}://{parts.netloc}"


def _revision_attempt(fetch: Fetch, base: str, expected: str) -> str | None:
    """Return None when the expected revision is live, else the reason it is not."""
    try:
        reply = fetch(f"{base}/healthz")
    except FetchError as error:
        return f"transport error: {error}"
    if reply.status != HTTP_OK:
        return f"/healthz answered HTTP {reply.status}"
    try:
        body = json.loads(reply.body)
    except ValueError:
        return "/healthz body is not JSON"
    if not isinstance(body, dict) or body.get("status") != "ok":
        return f"health status is {body.get('status') if isinstance(body, dict) else body!r}"
    if body.get("revision") != expected:
        return f"revision is {body.get('revision')!r}, expected {expected!r}"
    return None


def _with_retry(attempt: Callable[[], str | None], retry: Retry) -> str | None:
    """Return None on the first successful attempt, else the last failure reason."""
    reason: str | None = "no attempt made"
    for number in range(1, retry.attempts + 1):
        reason = attempt()
        if reason is None:
            return None
        if number < retry.attempts:
            retry.sleep(retry.interval)
    return reason


def check_revision(fetch: Fetch, base: str, expected: str, retry: Retry) -> CheckResult:
    """``/healthz`` must expose ``expected`` within ``retry.attempts`` tries."""
    reason = _with_retry(lambda: _revision_attempt(fetch, base, expected), retry)
    if reason is None:
        return CheckResult("revision", True, f"{expected} is live")
    return CheckResult(
        "revision", False, f"{expected} not live after {retry.attempts} attempt(s): {reason}"
    )


def _public_attempt(fetch: Fetch, base: str, path: str) -> str | None:
    try:
        reply = fetch(f"{base}{path}")
    except FetchError as error:
        return f"transport error: {error}"
    if reply.status != HTTP_OK:
        return f"{path} answered HTTP {reply.status}, expected 200"
    return None


def check_public(fetch: Fetch, base: str, path: str, retry: Retry) -> CheckResult:
    """A public route must answer 200 within ``retry.attempts`` tries."""
    name = f"public {path}"
    reason = _with_retry(lambda: _public_attempt(fetch, base, path), retry)
    if reason is None:
        return CheckResult(name, True, f"{path} answered 200")
    return CheckResult(name, False, reason)


def _points_to_login(location: str, base: str) -> bool:
    """True for ``/login`` reached by a relative Location or on the base origin."""
    target, home = urlsplit(location), urlsplit(base)
    if target.scheme or target.netloc:
        same_origin = (target.scheme.lower(), target.netloc.lower()) == (
            home.scheme.lower(),
            home.netloc.lower(),
        )
        if not same_origin:
            return False
    return target.path == LOGIN_PATH


def _protected_attempt(fetch: Fetch, base: str, path: str) -> str | None:
    try:
        reply = fetch(f"{base}{path}")
    except FetchError as error:
        return f"transport error: {error}"
    if reply.status >= SERVER_ERROR_FLOOR:
        return f"{path} answered HTTP {reply.status} (server error)"
    if reply.status not in REDIRECT_STATUSES:
        return f"{path} answered HTTP {reply.status}, expected a redirect to {LOGIN_PATH}"
    if not reply.location or not _points_to_login(reply.location, base):
        return f"{path} redirects to {reply.location!r}, expected {LOGIN_PATH} on {base}"
    return None


def check_protected(fetch: Fetch, base: str, path: str, retry: Retry) -> CheckResult:
    """A protected route must redirect an anonymous caller to ``/login`` on this origin."""
    name = f"protected {path} redirect"
    reason = _with_retry(lambda: _protected_attempt(fetch, base, path), retry)
    if reason is None:
        return CheckResult(name, True, f"{path} redirects to {LOGIN_PATH}")
    return CheckResult(name, False, reason)


def run_smoke(fetch: Fetch, base: str, revision: str, retry: Retry) -> list[CheckResult]:
    """Run every check (no short-circuit, so one run reports every failure)."""
    return [
        check_revision(fetch, base, revision, retry),
        check_public(fetch, base, LOGIN_PATH, retry),
        check_protected(fetch, base, PROTECTED_PATH, retry),
    ]


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--health-url", required=True, help="public /healthz URL")
    parser.add_argument("--revision", required=True, help="expected deployed SHA")
    parser.add_argument("--attempts", type=int, default=6, help="tries per check (>= 1)")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between tries (>= 0)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the smoke and return the exit code documented in the module docstring."""
    _pin_output_encoding()
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return EXIT_USAGE_ERROR
    try:
        base = origin(args.health_url)
    except ValueError as error:
        print(f"::error::usage: {error}")
        return EXIT_USAGE_ERROR
    if args.attempts < 1 or args.interval < 0:
        print("::error::usage: --attempts must be >= 1 and --interval >= 0")
        return EXIT_USAGE_ERROR

    results = run_smoke(fetch_url, base, args.revision, Retry(args.attempts, args.interval))
    failed = [result for result in results if not result.ok]
    for result in results:
        if result.ok:
            print(f"ok    {result.name}: {result.detail}")
        else:
            print(f"::error::smoke check '{result.name}' failed: {result.detail}")
    if failed:
        return EXIT_FAILED
    print(f"::notice::production smoke passed for {args.revision}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
