"""Unit tests for the verify-state binding helpers (issue #1004).

Covers the login-CSRF helpers added to ``app.core.local_backend.magic_link``:

- ``_issue_state`` — fresh URL-safe entropy per call, binding stored
  with the token HASH (never the raw token) and the 30-min TTL, and
  pruning of expired bindings.
- ``_consume_state`` — fail closed on missing / unknown / expired
  state and on a state presented over a different token; single-use by
  construction (a failed verify also spends the binding).

The route-level behaviour (real app, real Postgres, attacker
scenarios) is covered by ``tests/integration/test_magic_link_state.py``.
"""
from __future__ import annotations

import hashlib

from fastapi import FastAPI

from app.core.local_backend.magic_link import (
    _STATE_TTL_SECONDS,
    _consume_state,
    _issue_state,
    _state_store,
)

_TOKEN = "a" * 64
_OTHER_TOKEN = "b" * 64


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


# --- _issue_state ---------------------------------------------------------------


def test_issue_state_returns_fresh_urlsafe_entropy() -> None:
    """Every state is new 256-bit URL-safe entropy, never reused."""
    app = FastAPI()
    first = _issue_state(app, _TOKEN)
    second = _issue_state(app, _TOKEN)

    assert first != second
    assert len(first) >= 32
    assert all(c.isalnum() or c in "-_" for c in first)


def test_issue_state_binds_token_hash_not_raw_token() -> None:
    """The binding stores the token HASH; the raw token never lands in
    the store (mirrors the port's SHA-256-only posture)."""
    app = FastAPI()
    state = _issue_state(app, _TOKEN)

    binding = _state_store(app)[state]
    assert binding.token_hash == _token_hash(_TOKEN)
    assert binding.expires_at > 0
    assert _STATE_TTL_SECONDS == 1800  # same TTL pattern as the port


def test_issue_state_prunes_expired_bindings() -> None:
    """Issuing a new state drops already-expired bindings so the store
    cannot grow without bound."""
    app = FastAPI()
    stale = _issue_state(app, _TOKEN)
    _state_store(app)[stale] = _state_store(app)[stale]._replace(expires_at=0.0)

    _issue_state(app, _TOKEN)

    assert stale not in _state_store(app)


# --- _consume_state ---------------------------------------------------------------


def test_consume_state_accepts_the_one_valid_use() -> None:
    app = FastAPI()
    state = _issue_state(app, _TOKEN)

    assert _consume_state(app, state, _TOKEN) is True
    # Single-use: the binding was spent by the first call.
    assert state not in _state_store(app)


def test_consume_state_fails_closed_on_missing_value() -> None:
    """Both ``None`` (param absent) and ``""`` fail closed."""
    app = FastAPI()
    _issue_state(app, _TOKEN)

    assert _consume_state(app, None, _TOKEN) is False
    assert _consume_state(app, "", _TOKEN) is False


def test_consume_state_fails_closed_on_unknown_value() -> None:
    app = FastAPI()
    _issue_state(app, _TOKEN)

    assert _consume_state(app, "A" * 43, _TOKEN) is False


def test_consume_state_fails_closed_on_expired_binding() -> None:
    """A state past its TTL is rejected even over the correct token."""
    app = FastAPI()
    state = _issue_state(app, _TOKEN)
    _state_store(app)[state] = _state_store(app)[state]._replace(expires_at=0.0)

    assert _consume_state(app, state, _TOKEN) is False


def test_consume_state_rejects_state_bound_to_other_token() -> None:
    """A state is only valid over the exact token it was minted for."""
    app = FastAPI()
    state = _issue_state(app, _TOKEN)

    assert _consume_state(app, state, _OTHER_TOKEN) is False
    # The failed use still spent the binding (single-use by design).
    assert state not in _state_store(app)


def test_consume_state_replay_finds_empty_store() -> None:
    """Replaying a consumed state is indistinguishable from an unknown
    value: fail closed, no cookie-shape side effects."""
    app = FastAPI()
    state = _issue_state(app, _TOKEN)
    assert _consume_state(app, state, _TOKEN) is True

    assert _consume_state(app, state, _TOKEN) is False
