"""Tests for the rawsql auth gate (issue #680).

Covers the default-deny behaviour: the handler must reject every
request that does not present a ``Authorization: Bearer <token>``
header matching :attr:`Settings.rawsql_auth_token`. The comparison
itself is unit-tested here (constant-time, exact match, header
parsing); the live HTTP integration lives in
``tests/integration/test_local_backend.py`` under the same
``APAP_RAWSQL_AUTH_TOKEN`` env var.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.core.local_backend.rawsql import _require_rawsql_token


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the lru_cache between cases so each env mutation is observed."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_token(value: str) -> None:
    """Replace the cached ``Settings`` instance with one carrying the given token.

    ``Settings`` reads ``APAP_*`` env vars at construction; mutating
    ``os.environ`` after the fact is not enough — the lru_cache must
    be cleared so the next ``get_settings()`` rebuilds. Doing the
    rebuild here keeps the test bodies focused on the auth gate.
    """
    import os

    if value:
        os.environ["APAP_RAWSQL_AUTH_TOKEN"] = value
    else:
        os.environ.pop("APAP_RAWSQL_AUTH_TOKEN", None)
    get_settings.cache_clear()


def _settings(token: str) -> Settings:
    _set_token(token)
    return get_settings()


class TestRawsqlAuthGate:
    """Default-deny: every unmatched presentation must raise 401 BEFORE any DB call."""

    def test_missing_header_with_configured_token(self) -> None:
        from fastapi import HTTPException

        settings = _settings("a" * 40)
        token = settings.rawsql_auth_token
        assert token is not None and len(token) >= 32  # sanity: token is set
        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization=None)
        assert exc.value.status_code == 401
        assert "missing" in exc.value.detail.lower()
        assert (exc.value.headers or {}).get("WWW-Authenticate") == "Bearer"

    def test_empty_header_with_configured_token(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization="")
        assert exc.value.status_code == 401
        assert "missing" in exc.value.detail.lower()

    def test_wrong_scheme_rejected(self) -> None:
        """Basic, Token, etc. must all be rejected — only ``Bearer`` is accepted."""
        from fastapi import HTTPException

        _settings("a" * 40)
        for wrong in ("Basic Zm9vOmJhcg==", "Token abc", "Digest foo", "bearer abc"):
            with pytest.raises(HTTPException) as exc:
                _require_rawsql_token(authorization=wrong)
            assert exc.value.status_code == 401, wrong

    def test_correct_token_passes_silently(self) -> None:
        _settings("a" * 40)
        # No exception == success; the helper is the only contract here.
        _require_rawsql_token(authorization="Bearer " + "a" * 40)

    def test_token_with_trailing_whitespace_still_passes(self) -> None:
        """``Bearer `` is one space; FastAPI trims trailing whitespace only.

        The helper does ``removeprefix("Bearer ").strip()`` so callers
        with extra trailing whitespace (some HTTP clients add it
        around credentials) still authenticate. Leading whitespace is
        rejected because the header scheme detection uses
        ``startswith("Bearer ")`` and the spec disallows it.
        """
        _settings("a" * 40)
        _require_rawsql_token(authorization="Bearer " + "a" * 40 + "   ")

    def test_close_but_wrong_token_rejected(self) -> None:
        """Default-deny: a token that differs by ONE character is rejected."""
        from fastapi import HTTPException

        _settings("a" * 40)
        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization="Bearer " + "a" * 39 + "b")
        assert exc.value.status_code == 401
        assert "invalid" in exc.value.detail.lower()

    def test_empty_configured_token_rejects_every_request(self) -> None:
        """Server has no token configured → every request denied (default-deny)."""
        from fastapi import HTTPException

        _settings("")
        # Even a well-formed bearer is rejected — the gate denies
        # because the server has no expected token to compare against.
        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization="Bearer anything")
        assert exc.value.status_code == 401
        assert "disabled" in exc.value.detail.lower()

    def test_empty_token_rejected_even_with_empty_header(self) -> None:
        """Double-empty: no env var, no Authorization header → still 401."""
        from fastapi import HTTPException

        _settings("")
        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization=None)
        assert exc.value.status_code == 401

    def test_constant_time_comparison_used(self) -> None:
        """The handler must not short-circuit on shared prefix.

        ``hmac.compare_digest`` does not reveal length-prefix matches
        via timing; we only assert the BEHAVIOUR (every prefix mismatch
        is denied) here. The exact constant-time property is the
        stdlib's contract, not ours.
        """
        from fastapi import HTTPException

        _settings("abcdefghij" + "X" * 30)
        # Pass the wrong token that happens to share the prefix; must deny.
        with pytest.raises(HTTPException) as exc:
            _require_rawsql_token(authorization="Bearer abcdefghij")
        assert exc.value.status_code == 401
