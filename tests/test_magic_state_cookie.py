"""Unit tests for the magic-link state-cookie browser binding.

Issue #1004 round-1 fix: :mod:`app.core.local_backend.state_cookie`
binds the emailed verify URL to the browser that requested the link.
These atoms pin the pure helper contract without DB, lifespan or
router: presence, equality (timing-safe path), and the fail-closed
shape when either half of the binding is missing.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from app.core.local_backend.state_cookie import (
    MAGIC_STATE_COOKIE_NAME,
    MAGIC_STATE_COOKIE_PATH,
    expire_state_cookie,
    set_state_cookie,
    state_cookie_matches,
)


def _request_with_cookie(cookie_header: str | None) -> Request:
    """Build a minimal starlette Request carrying one Cookie header."""
    headers = []
    if cookie_header is not None:
        headers.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": MAGIC_STATE_COOKIE_PATH + "/verify",
        "headers": headers,
    }
    return Request(scope)


class TestStateCookieMatches:
    """The browser binding: URL state vs cookie, fail closed on any miss."""

    def test_matches_when_cookie_equals_url_state(self) -> None:
        request = _request_with_cookie(f"{MAGIC_STATE_COOKIE_NAME}=s3cr3t")
        assert state_cookie_matches(request, "s3cr3t") is True

    def test_fails_closed_on_missing_cookie(self) -> None:
        # The forwarded-URL attack shape: victim's browser has no cookie.
        request = _request_with_cookie(None)
        assert state_cookie_matches(request, "s3cr3t") is False

    def test_fails_closed_on_missing_url_state(self) -> None:
        request = _request_with_cookie(f"{MAGIC_STATE_COOKIE_NAME}=s3cr3t")
        assert state_cookie_matches(request, None) is False

    def test_fails_closed_on_value_mismatch(self) -> None:
        request = _request_with_cookie(f"{MAGIC_STATE_COOKIE_NAME}=s3cr3t")
        assert state_cookie_matches(request, "other") is False


class TestSetAndExpireStateCookie:
    """Cookie flags set by /start and the expiry emitted on success."""

    def test_set_state_cookie_flags(self) -> None:
        response = Response()
        set_state_cookie(response, "s3cr3t", max_age=1800)
        set_cookie = response.headers["set-cookie"]
        assert f"{MAGIC_STATE_COOKIE_NAME}=s3cr3t" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert f"Path={MAGIC_STATE_COOKIE_PATH}" in set_cookie
        assert "Max-Age=1800" in set_cookie

    def test_expire_state_cookie_zeroes_max_age(self) -> None:
        response = Response()
        expire_state_cookie(response)
        set_cookie = response.headers["set-cookie"]
        assert 'apap_magic_state=""' in set_cookie
        assert "Max-Age=0" in set_cookie
        assert f"Path={MAGIC_STATE_COOKIE_PATH}" in set_cookie
