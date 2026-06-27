"""Signed cookie session helpers.

APAP_WEB uses signed cookies (via ``itsdangerous``) for the session
instead of a server-side store. The cookie carries just the user
identity; per-request authorization is enforced by the auth
middleware by looking up the email in the ``authorized_users`` table.

We use :class:`itsdangerous.URLSafeTimedSerializer` rather than the
lower-level :class:`TimestampSigner` because the URL-safe serializer
emits tokens that contain only ``[A-Za-z0-9_-=]`` — no commas, no
quotes, no backslashes. That is the format the HTTP cookie spec
demands for unquoted ``Set-Cookie`` values, and what ``httpx``'s
client cookie jar can store verbatim. Using ``TimestampSigner`` would
force Starlette to quote the value (with backslash-escaped JSON),
which ``httpx`` then fails to unquote reliably.

The signing secret is read from :attr:`Settings.session_secret`. In
production it must be a long random value; the default is only safe
for development.
"""

from __future__ import annotations

from typing import Any

import itsdangerous

_SESSION_COOKIE_NAME = "apap_session"
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # one week


def session_cookie_name() -> str:
    """Return the cookie name (public for tests and middleware)."""
    return _SESSION_COOKIE_NAME


def _signer(secret: str) -> itsdangerous.URLSafeTimedSerializer:
    return itsdangerous.URLSafeTimedSerializer(secret)


def write_session(payload: dict[str, Any], *, secret: str) -> str:
    """Serialize and sign a session payload as a cookie value."""
    return _signer(secret).dumps(payload)


def read_session(token: str, *, secret: str) -> dict[str, Any] | None:
    """Verify the signature and return the payload, or None on any failure.

    Failures (bad signature, expired timestamp, malformed JSON) all
    return ``None`` so the caller can treat the user as logged out
    without catching exceptions.
    """
    try:
        decoded = _signer(secret).loads(token, max_age=_SESSION_MAX_AGE_SECONDS)
    except (itsdangerous.BadSignature, itsdangerous.SignatureExpired):
        return None
    return decoded if isinstance(decoded, dict) else None


def clear_session_cookie_params() -> dict[str, Any]:
    """Return the kwargs needed to expire the session cookie via ``set_cookie``.

    Starlette's ``Response.delete_cookie`` has no ``max_age`` parameter;
    to expire a cookie you must ``set_cookie(key, value="", max_age=0)``.

    ``samesite="strict"`` (PR-5B, REQ-AH-5) closes the CSRF gap that
    ``lax`` leaves open for top-level cross-site POSTs. The CSRF
    middleware (``app/core/csrf.py``) is the secondary defense for
    browsers that do not honor Strict.
    """
    return {
        "key": _SESSION_COOKIE_NAME,
        "value": "",
        "max_age": 0,
        "path": "/",
        "httponly": True,
        "secure": True,
        "samesite": "strict",
    }
