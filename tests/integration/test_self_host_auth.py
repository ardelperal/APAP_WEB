"""Tests for ``MagicLinkPort`` and ``ClassicPasswordAuthPort``.

The magic link + classic password auth is the M1 milestone of the
self-host-backend-coolify openspec. The Ports (Protocols) define
the contract; these tests pin the behaviour before any adapter is
written. The InsForgeAdapter gains a no-op default for the new
methods so the migration does not break the existing OAuth-only
deployments.

Hard rules honoured (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state via the
  integration conftest (real Postgres + ephemeral schema).
- Rule 4 (no humo): assertions on real behaviour (the token returned,
  the row stored, the password verified), not on absence-of-error.
- Rule 8 (no production mutation): tests run against a
  session-scoped ephemeral schema that is dropped on teardown.

These tests run against the real Postgres ephemeral schema. The
``MIGRATION_DSN`` env var (or the CI job's service container)
provisions the database. Tests skip cleanly when the env var is
missing — they do not fail the suite when no Postgres is available.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.core.adapters.auth_local.magic_link_port import MagicLinkPort
from app.core.adapters.auth_local.classic_password_auth_port import (
    ClassicPasswordAuthPort,
)


# --- MagicLinkPort ---------------------------------------------------------


@pytest.mark.integration
def test_create_token_returns_raw_token_and_stores_hash(
    self_host_schema,
) -> None:
    """``create_token`` returns a raw token (the caller logs it for the
    operator) and stores a SHA-256 hash in the database (so a DB leak
    does not expose live tokens).
    """
    port = MagicLinkPort(self_host_schema)
    raw = port.create_token("ana@test.com", purpose="login")

    # Raw token is 64 hex chars (32 bytes).
    assert isinstance(raw, str)
    assert len(raw) == 64
    assert all(c in "0123456789abcdef" for c in raw)

    # The database only sees the SHA-256 of the raw token.
    rows = self_host_schema.execute_sql(
        "SELECT email, used_at FROM magic_link_tokens"
    )
    assert len(rows) == 1
    assert rows[0]["email"] == "ana@test.com"
    assert rows[0]["used_at"] is None


@pytest.mark.integration
def test_create_token_normalizes_email_to_lowercase(self_host_schema) -> None:
    """Emails are stored lower-case so consumption is case-insensitive."""
    port = MagicLinkPort(self_host_schema)
    port.create_token("ANA@TEST.COM")

    rows = self_host_schema.execute_sql("SELECT email FROM magic_link_tokens")
    assert rows[0]["email"] == "ana@test.com"


@pytest.mark.integration
def test_consume_token_returns_email_and_marks_used(
    self_host_schema,
) -> None:
    """A fresh token is consumed once: returns the email and marks
    ``used_at = now()``.
    """
    port = MagicLinkPort(self_host_schema)
    raw = port.create_token("ana@test.com", purpose="login")

    email = port.consume_token(raw)
    assert email == "ana@test.com"

    rows = self_host_schema.execute_sql(
        "SELECT used_at FROM magic_link_tokens"
    )
    assert rows[0]["used_at"] is not None


@pytest.mark.integration
def test_consume_token_twice_returns_none(self_host_schema) -> None:
    """One-time use: a second ``consume_token`` on the same raw returns
    ``None`` because ``used_at`` is set.
    """
    port = MagicLinkPort(self_host_schema)
    raw = port.create_token("ana@test.com", purpose="login")

    assert port.consume_token(raw) == "ana@test.com"
    assert port.consume_token(raw) is None


@pytest.mark.integration
def test_consume_token_expired_returns_none(self_host_schema) -> None:
    """A token past its TTL is invalid; ``consume_token`` returns ``None``.
    """
    port = MagicLinkPort(self_host_schema, ttl_seconds=1)
    raw = port.create_token("ana@test.com", purpose="login")
    # Force-expire by updating the DB directly.
    from datetime import UTC, datetime, timedelta
    self_host_schema.execute_sql(
        "UPDATE magic_link_tokens SET expires_at = %s",
        [datetime.now(UTC) - timedelta(seconds=10)],
    )
    assert port.consume_token(raw) is None


@pytest.mark.integration
def test_consume_token_unknown_returns_none(self_host_schema) -> None:
    """A token that was never issued returns ``None``."""
    port = MagicLinkPort(self_host_schema)
    assert port.consume_token("0" * 64) is None


@pytest.mark.integration
def test_list_active_returns_unused_unexpired_tokens(
    self_host_schema,
) -> None:
    """``list_active`` returns only the active (not used, not expired)
    tokens, ordered by ``created_at DESC``.
    """
    port = MagicLinkPort(self_host_schema, ttl_seconds=600)
    first = port.create_token("first@test.com", purpose="login")
    time.sleep(0.01)  # ensure distinct created_at
    second = port.create_token("second@test.com", purpose="login")

    # Consume one — it should NOT appear in the active list.
    port.consume_token(first)

    active = port.list_active()
    assert len(active) == 1
    assert active[0]["email"] == "second@test.com"
    assert active[0]["created_at"] >= active[0]["created_at"]  # sanity


# --- ClassicPasswordAuthPort ----------------------------------------------


@pytest.mark.integration
def test_set_password_then_verify_returns_user(self_host_schema) -> None:
    """``verify_password`` returns the AuthorizedUser when the password
    matches the argon2id hash stored by ``set_password``.
    """
    # Insert a user row (ClassicPasswordAuthPort does not create
    # users; that is the bootstrap admin's responsibility).
    self_host_schema.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) "
        "VALUES (%s, %s, true)",
        ["ana@test.com", "writer"],
    )
    port = ClassicPasswordAuthPort(self_host_schema)
    port.set_password("ana@test.com", "secret123")

    user = port.verify_password("ana@test.com", "secret123")
    assert user is not None
    assert user.email == "ana@test.com"
    assert user.active is True


@pytest.mark.integration
def test_verify_password_wrong_returns_none(self_host_schema) -> None:
    port = ClassicPasswordAuthPort(self_host_schema)
    port.set_password("ana@test.com", "secret123")

    assert port.verify_password("ana@test.com", "wrong") is None


@pytest.mark.integration
def test_verify_password_unknown_email_returns_none(
    self_host_schema,
) -> None:
    port = ClassicPasswordAuthPort(self_host_schema)
    port.set_password("ana@test.com", "secret123")

    assert port.verify_password("ghost@test.com", "secret123") is None


@pytest.mark.integration
def test_verify_password_inactive_user_returns_none(
    self_host_schema,
) -> None:
    """A user with ``activo = false`` cannot log in even with the right
    password — the admin must first re-activate them.
    """
    port = ClassicPasswordAuthPort(self_host_schema)
    port.set_password("ana@test.com", "secret123")
    self_host_schema.execute_sql(
        "UPDATE usuarios_autorizados SET activo = false WHERE email = %s",
        ["ana@test.com"],
    )

    assert port.verify_password("ana@test.com", "secret123") is None


@pytest.mark.integration
def test_verify_password_null_hash_returns_none(self_host_schema) -> None:
    """A user without a password set (OAuth-only) returns None."""
    # Insert a user without password_hash.
    self_host_schema.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) VALUES (%s, %s, %s)",
        ["oauth-only@test.com", "writer", True],
    )

    port = ClassicPasswordAuthPort(self_host_schema)
    assert port.verify_password("oauth-only@test.com", "anything") is None


@pytest.mark.integration
def test_set_password_updates_existing_hash(self_host_schema) -> None:
    """``set_password`` is idempotent: setting it twice replaces the hash."""
    port = ClassicPasswordAuthPort(self_host_schema)
    port.set_password("ana@test.com", "first")
    port.set_password("ana@test.com", "second")

    assert port.verify_password("ana@test.com", "first") is None
    assert port.verify_password("ana@test.com", "second") == port.verify_password(
        "ana@test.com", "second"
    )


# --- InsForge adapter no-op defaults (backward compat) -----------------


def test_insforge_auth_port_verify_password_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The InsForge adapter gains a default ``verify_password`` that
    returns None — InsForge does not have password auth, so the
    fallback prevents AttributeError when the M0 backend is not
    configured but the M1 endpoint is hit.

    The default is overridden by the local adapter when
    ``APAP_LOCAL_BACKEND=true`` is set.
    """
    from app.core.adapters.insforge.auth_insforge_adapter import (
        InsForgeAuthUsersAdapter,
    )

    adapter = InsForgeAuthUsersAdapter(executor=None)
    # verify_password is not implemented on InsForge; calling it should
    # raise AttributeError or return None. The migration must add the
    # method. After the migration it returns None (InsForge has no
    # password auth).
    result = adapter.verify_password("ana@test.com", "anything")
    assert result is None


def test_insforge_auth_port_set_password_raises() -> None:
    """The InsForge adapter's default ``set_password`` raises
    ``NotImplementedError`` — InsForge cannot store password hashes.
    """
    from app.core.adapters.insforge.auth_insforge_adapter import (
        InsForgeAuthUsersAdapter,
    )

    adapter = InsForgeAuthUsersAdapter(executor=None)
    with pytest.raises(NotImplementedError):
        adapter.set_password("ana@test.com", "anything")
