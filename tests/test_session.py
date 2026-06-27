"""Tests for the signed cookie session and PKCE helpers."""

from __future__ import annotations

from app.core.pkce import generate_pkce_pair
from app.core.session import (
    clear_session_cookie_params,
    read_session,
    session_cookie_name,
    write_session,
)


def test_generate_pkce_pair_returns_verifier_and_challenge() -> None:
    """The PKCE pair has a non-empty verifier and a distinct challenge."""
    verifier, challenge = generate_pkce_pair()

    assert len(verifier) >= 43
    assert len(challenge) >= 43
    assert verifier != challenge


def test_generate_pkce_pair_is_unpredictable() -> None:
    """Two calls produce different pairs (random under the hood)."""
    v1, c1 = generate_pkce_pair()
    v2, c2 = generate_pkce_pair()

    assert (v1, c1) != (v2, c2)


def test_session_round_trip_preserves_payload() -> None:
    """A payload encoded with ``write_session`` decodes back identically."""
    secret = "test-secret"
    payload = {"email": "a@b.com", "rol": "developer", "user_id": "u-1"}

    token = write_session(payload, secret=secret)
    decoded = read_session(token, secret=secret)

    assert decoded == payload


def test_session_read_rejects_wrong_secret() -> None:
    """A token signed with one secret is rejected when decoded with another."""
    token = write_session({"email": "a@b.com"}, secret="secret-A")

    assert read_session(token, secret="secret-B") is None


def test_session_read_rejects_tampered_token() -> None:
    """A tampered token is rejected."""
    token = write_session({"email": "a@b.com"}, secret="test-secret")
    tampered = token[:-2] + "XX"

    assert read_session(tampered, secret="test-secret") is None


def test_session_cookie_name_is_stable() -> None:
    """The cookie name is part of the public contract; it must not change silently."""
    assert session_cookie_name() == "apap_session"


def test_clear_session_cookie_params_expire_session() -> None:
    """``clear_session_cookie_params`` returns the kwargs to expire the session cookie."""
    params = clear_session_cookie_params()

    assert params["key"] == session_cookie_name()
    assert params["value"] == ""
    assert params["max_age"] == 0
    assert params["path"] == "/"
    assert params["httponly"] is True


# --- PR-5B (hardening-2026-q2): SameSite=Strict (REQ-AH-5) -----------------
#
# ``apap_session`` and ``apap_pkce`` cookies now ship with
# ``samesite="strict"`` to prevent cross-site form submission. Lax still
# allows top-level POSTs to slip through; Strict is the only setting
# that closes the gap. The CSRF middleware (REQ-AH-8) is the defense
# for non-strict browsers.


def test_clear_session_cookie_params_uses_samesite_strict() -> None:
    """``clear_session_cookie_params`` ships ``samesite="strict"`` (REQ-AH-5).

    This is the spec contract — logout's ``Set-Cookie: apap_session=...``
    MUST carry ``SameSite=Strict`` so that a logged-out cookie cannot
    be replayed by a cross-site form submission.
    """
    params = clear_session_cookie_params()

    assert params["samesite"] == "strict"
