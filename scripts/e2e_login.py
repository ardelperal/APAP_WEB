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

    Prefers the ``Expires`` HTTP-date; falls back to ``Max-Age`` so the
    minted storageState keeps the server's intended lifetime (the mock's
    session cookie uses ``Max-Age``, and dropping it would downgrade a
    7-day cookie to a browser-session cookie). Unknown/invalid values
    degrade to ``-1`` (session cookie), which Playwright accepts.
    """
    from email.utils import parsedate_to_datetime

    if raw:
        try:
            return int(parsedate_to_datetime(raw).timestamp())
        except (TypeError, ValueError):
            return -1
    try:
        seconds = int(max_age)
    except (TypeError, ValueError):
        return -1
    if seconds < 0:
        return -1
    return int(time.time()) + seconds


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
                    "secure": bool(morsel["secure"]),
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
            "auth is enabled on the target"
        )
    state = _build_storage_state(response, base_url)
    _write_0600(Path(out_path), state)
    return state


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
    print(f"storageState written to {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin argv wrapper
    raise SystemExit(main())
