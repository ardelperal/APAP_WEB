#!/usr/bin/env python3
"""E2E login CLI: mint a Playwright storageState via the test-only mock (issue #906).

The E2E suites need an authenticated session without walking the Google
OAuth flow. ``app/core/e2e_auth.py`` exposes ``GET /e2e/login``, which
mints a signed session cookie when called with the ``X-E2E-Secret``
header. Before this CLI every Playwright suite repeated its own ad-hoc
login preflight; this script turns that into the standard Playwright
pattern: login once, write a ``storageState`` file, and let every
``browser.new_context(storage_state=...)`` start authenticated — against
any environment (local, CI station, or a release-gated deployment).

Contract:

- The secret is read from the environment variable named by
  ``--secret-env``. It NEVER travels through argv, and it is never
  printed — not on success and not on failure.
- The response must carry the ``apap_session`` cookie; anything else is
  an error (missing cookie, non-200 status) with a clear message.
- The storageState is written with permissions ``0600``: it contains a
  live session cookie, so it must be readable only by the operator.
- ``origins`` is emitted empty: the mock mints no localStorage. The
  file therefore contains session cookies only.

The core logic lives in :func:`mint_storage_state` (importable, so
``tests/e2e/conftest.py`` can share one minted state per pytest session
without shelling out) and :func:`main` is the thin argv wrapper.

Exit codes: ``0`` on success, ``1`` on any login/storageState error
(message on stderr), ``2`` on usage errors (argparse's own).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

import httpx

E2E_LOGIN_PATH = "/e2e/login"
# Sentinel name shared with app.core.e2e_auth / app.core.session.
# Duplicated on purpose: the CLI must run against any environment and
# must not import the application package to stay transport-agnostic.
SESSION_COOKIE_NAME = "apap_session"
# Header NAME, not a credential — the value always comes from the env.
E2E_SECRET_HEADER = "X-E2E-Secret"  # noqa: S105 — header name, not a secret literal


class E2eLoginError(RuntimeError):
    """Base class for every e2e-login failure surfaced to the operator."""


class MissingSecretError(E2eLoginError):
    """The secret environment variable named by --secret-env is unset/empty."""


class LoginFailedError(E2eLoginError):
    """The /e2e/login endpoint rejected the request (non-200)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        # Lets callers (e.g. the pytest fixture skip policy) distinguish
        # benign statuses (404 — e2e mock disabled on the target) from
        # fatal ones (401 — wrong/stale secret) without parsing messages.
        self.status_code = status_code


class SessionCookieError(E2eLoginError):
    """The response did not carry the expected session cookie."""


def _read_secret(secret_env: str) -> str:
    """Return the shared secret read from the named environment variable.

    The variable NAME is safe to print; the VALUE never is. An unset or
    empty variable is an operator error, not an anonymous failure.
    """
    secret = os.environ.get(secret_env)
    if not secret:
        raise MissingSecretError(  # noqa: TRY003 — operator-facing diagnostic
            f"environment variable {secret_env!r} is not set or empty; "
            f"export it (the {E2E_SECRET_HEADER} value) before running e2e_login"
        )
    return secret


def _parse_expires(raw: str, max_age: str) -> int:
    """Convert cookie lifetime attributes to epoch seconds (-1 for session cookies).

    RFC 6265 section 5.2.2 precedence: a valid ``Max-Age`` wins over
    ``Expires`` when both are present (issue #906 fix round 1 — the
    previous order inverted the RFC). Falls back to the ``Expires``
    HTTP-date, then degrades to ``-1`` (session cookie), which Playwright
    accepts. Honoring ``Max-Age`` matters: the mock's session cookie uses
    it, and dropping it would downgrade a 7-day cookie to a browser-
    session cookie.
    """
    from email.utils import parsedate_to_datetime

    try:
        seconds = int(max_age)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None and seconds >= 0:
        return int(time.time()) + seconds
    if raw:
        try:
            return int(parsedate_to_datetime(raw).timestamp())
        except (TypeError, ValueError):
            return -1
    return -1


def _same_site(raw: str) -> str:
    """Normalize a SameSite attribute to Playwright's vocabulary."""
    return {"strict": "Strict", "lax": "Lax", "none": "None"}.get(raw.strip().lower(), "Lax")


def _build_storage_state(response: httpx.Response, request_url: str) -> dict[str, object]:
    """Extract the session cookie into a Playwright-compatible storageState.

    Raises :class:`SessionCookieError` when the response carries no
    ``apap_session`` cookie — a 200 without a cookie means the mock did
    not mint a session and the file would silently authenticate nothing.
    """
    parsed = urlparse(request_url)
    host = parsed.hostname or "127.0.0.1"
    # The storageState cookie's Secure flag is derived from the request
    # URL's scheme, NOT copied from the Set-Cookie header (issue #906,
    # fix F2): the server sets secure=not settings.debug for its own
    # deployment, and Chromium silently drops Secure cookies set against
    # plain-http origins — the minted storageState would authenticate
    # nothing while the CLI exits 0. The cookie must be valid for the
    # origin the browser will actually replay it against.
    secure = parsed.scheme == "https"
    cookies: list[dict[str, object]] = []
    for header in response.headers.get_list("set-cookie"):
        jar: SimpleCookie = SimpleCookie()
        jar.load(header)
        for key, morsel in jar.items():
            if key != SESSION_COOKIE_NAME:
                continue
            cookies.append(
                {
                    "name": key,
                    "value": morsel.value,
                    # Host-only cookies (no Domain attribute) are scoped to
                    # the request host, which is what Playwright expects.
                    "domain": morsel["domain"] or host,
                    "path": morsel["path"] or "/",
                    "expires": _parse_expires(morsel["expires"], morsel["max-age"]),
                    "httpOnly": bool(morsel["httponly"]),
                    "secure": secure,
                    "sameSite": _same_site(morsel["samesite"]),
                }
            )
    if not cookies:
        raise SessionCookieError(  # noqa: TRY003 — operator-facing diagnostic
            f"{E2E_LOGIN_PATH} returned {response.status_code} but set no "
            f"{SESSION_COOKIE_NAME!r} cookie; the session was not minted "
            "(check that e2e auth is enabled on the target environment)"
        )
    # Minimal origins: the mock mints no localStorage/ sessionStorage.
    return {"cookies": cookies, "origins": []}


def _write_0600(path: Path, state: dict[str, object]) -> None:
    """Write the storageState with owner-only permissions, enforcing 0600.

    ``os.open`` with mode ``0o600`` can still land wider under a lax
    umask, and an existing file keeps its old mode, so the chmod is the
    authoritative enforcement (the file holds a live session cookie).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    path.chmod(0o600)


def mint_storage_state(
    *,
    base_url: str,
    secret_env: str,
    email: str | None = None,
    out_path: str | os.PathLike[str],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Mint a session and write a Playwright storageState; returns the state.

    Dependency seam: ``transport`` lets tests inject ``httpx.MockTransport``
    (web-TDD discipline: services take their external dependencies as
    parameters) while production uses the default real transport.
    """
    secret = _read_secret(secret_env)
    base_url = base_url.rstrip("/")
    with httpx.Client(base_url=base_url, transport=transport) as client:
        params = {"email": email} if email else None
        response = client.get(
            E2E_LOGIN_PATH,
            params=params,
            headers={E2E_SECRET_HEADER: secret},
        )
    if response.status_code != HTTPStatus.OK:
        # Status code only: the body could change, and the secret must
        # never appear in any diagnostic output.
        raise LoginFailedError(  # noqa: TRY003 — operator-facing diagnostic
            f"{E2E_LOGIN_PATH} returned {response.status_code} "
            f"(expected {HTTPStatus.OK}); check X-E2E-Secret and that e2e "
            "auth is enabled on the target",
            status_code=response.status_code,
        )
    state = _build_storage_state(response, base_url)
    _write_0600(Path(out_path), state)
    return state


# The server keeps an in-process auth cache with a 300s TTL
# (``Settings.auth_cache_ttl_seconds``, app/core/config.py) and
# ``/e2e/login`` is what refreshes it. A storageState older than that
# still carries a valid 7-day cookie, but requests start bouncing 302
# to /login once the server-side cache entry expires. The fixture layer
# therefore re-mints strictly before the server TTL: 240s leaves a 60s
# safety margin (issue #906, fix F3).
AUTH_STATE_REFRESH_TTL_SECONDS = 240


def is_benign_login_failure(exc: BaseException) -> bool:
    """True when ``exc`` is benign for the e2e fixture skip policy (issue #906, F1).

    Benign — safe to ``pytest.skip`` — means the secret env var is absent
    (:class:`MissingSecretError`) or the endpoint answered 404 (the e2e
    mock is disabled on the target). Everything else — a 401 for a
    wrong/stale secret, a 503 for an empty server secret, transport
    errors — must fail the authenticated suite loudly instead of
    green-skipping. Lives here (not in the conftest) so it is importable
    without triggering the e2e package's module-level environment setup.
    """
    if isinstance(exc, MissingSecretError):
        return True
    return isinstance(exc, LoginFailedError) and exc.status_code == HTTPStatus.NOT_FOUND


class AuthStateCache:
    """TTL-aware cache for one minted Playwright storageState (issue #906, F3).

    ``ensure_fresh`` mints on first use and re-mints only when the cached
    mint is older than ``AUTH_STATE_REFRESH_TTL_SECONDS``, measured with a
    monotonic clock (``clock`` and ``transport`` are injectable seams for
    tests). The same output path is rewritten in place, so consumers
    holding the path keep seeing the freshest state without re-importing
    anything.
    """

    def __init__(
        self,
        *,
        base_url: str,
        secret_env: str,
        out_path: str | os.PathLike[str],
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url
        self.secret_env = secret_env
        self.out_path = Path(out_path)
        self.transport = transport
        self._clock = clock
        self._minted_at: float | None = None

    def ensure_fresh(self) -> Path:
        """Return the storageState path, re-minting when past the TTL."""
        now = self._clock()
        if self._minted_at is None or now - self._minted_at >= AUTH_STATE_REFRESH_TTL_SECONDS:
            mint_storage_state(
                base_url=self.base_url,
                secret_env=self.secret_env,
                email=None,
                out_path=self.out_path,
                transport=self.transport,
            )
            self._minted_at = now
        return self.out_path


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    _pin_output_encoding()
    parser = argparse.ArgumentParser(
        prog="e2e_login",
        description=(
            "Mint a Playwright storageState via GET /e2e/login "
            "(issue #906). The secret is read from the environment "
            "variable named by --secret-env, never from argv."
        ),
    )
    parser.add_argument(
        "--base-url", required=True, help="App base URL, e.g. http://127.0.0.1:8000"
    )
    parser.add_argument(
        "--secret-env",
        required=True,
        help="NAME of the environment variable holding the X-E2E-Secret value",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Email to mint the session for (defaults to the server's e2e default)",
    )
    parser.add_argument("--out", required=True, help="storageState output path (written 0600)")
    args = parser.parse_args(argv)

    try:
        mint_storage_state(
            base_url=args.base_url,
            secret_env=args.secret_env,
            email=args.email,
            out_path=args.out,
            transport=transport,
        )
    except E2eLoginError as exc:
        print(f"e2e_login: {exc}", file=sys.stderr)
        return 1
    except (httpx.HTTPError, OSError) as exc:
        # Transport/connection failures must honor the documented
        # "exit 1 with a message on stderr" contract instead of escaping
        # as a raw traceback (issue #906, fix F5). The secret travels in
        # a request header only — neither the URL nor these exception
        # messages can contain it.
        print(
            f"e2e_login: {E2E_LOGIN_PATH} unreachable at {args.base_url}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"storageState written to {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin argv wrapper
    raise SystemExit(main())
