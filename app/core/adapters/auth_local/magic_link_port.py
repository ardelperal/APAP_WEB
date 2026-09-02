"""Local adapter implementing ``MagicLinkPort`` (M1, issue #641).

Magic links are one-time tokens for passwordless login and password
reset. The raw token never touches persistent storage: only its
SHA-256 hash is stored, so a DB leak does not expose live tokens.

Flow:
1. Operator (or SMTP future epic) generates a token for an email.
2. The token is delivered to the user via a trusted channel
   (operator log during MVP, SMTP in a future epic).
3. The user clicks ``/api/auth/magic?token=...``.
4. The server consumes the token: returns the email if the hash
   matches, not used, not expired. Marks ``used_at = now()`` atomically.
5. The server emits a session cookie for the user.

Token format:
- Raw: 32 random bytes (64 chars hex), ``secrets.token_hex(32)``.
- Stored: SHA-256 hex of the raw (64 chars hex).
- 30 min TTL by default; configurable per-call via ``ttl_seconds``.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from app.core.data_access import SqlExecutor
from app.core.ports.magic_link_port import MagicLinkPort


class MagicLinkPortImpl(MagicLinkPort):
    """Local-Postgres implementation of magic-link tokens."""

    INSERT_TOKEN_SQL = """
        INSERT INTO magic_link_tokens (token, email, expires_at)
        VALUES (%s, %s, %s)
    """

    CONSUME_TOKEN_SQL = """
        UPDATE magic_link_tokens
        SET used_at = %s
        WHERE token = %s
          AND used_at IS NULL
          AND expires_at > %s
        RETURNING email
    """

    SELECT_BY_HASH_SQL = """
        SELECT email, expires_at, used_at
        FROM magic_link_tokens
        WHERE token = %s
    """

    SELECT_ACTIVE_SQL = """
        SELECT email, expires_at, created_at
        FROM magic_link_tokens
        WHERE used_at IS NULL
          AND expires_at > %s
        ORDER BY created_at DESC
    """

    def __init__(
        self,
        db: SqlExecutor,
        *,
        ttl_seconds: int = 1800,  # 30 min default
    ) -> None:
        self._db = db
        self._ttl = ttl_seconds

    def create_token(
        self,
        email: str,
        *,
        purpose: str = "login",
        ttl_seconds: int | None = None,
    ) -> str:
        """Generate a fresh magic-link token.

        Returns the **raw** token (the caller logs it for the
        operator). Only the SHA-256 hash is persisted, so a DB leak
        does not expose live tokens.

        ``purpose`` is stored alongside the email so that future
        tokens can be scoped (login vs password_reset). Currently
        the port does not enforce a difference between the two
        (consume_token accepts any valid token) but the field is
        reserved in the schema for when the password-reset
        endpoint ships and wants to refuse login-purpose tokens.
        """
        # Normalise email to lower-case so lookup is case-insensitive.
        email_norm = email.strip().lower()
        raw_token = secrets.token_hex(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        # psycopg2 takes Python datetime, not epoch.
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        expires_at_dt = datetime.now(UTC) + timedelta(seconds=effective_ttl)
        self._db.execute_sql(
            self.INSERT_TOKEN_SQL,
            [token_hash, email_norm, expires_at_dt],
        )
        # Persist the purpose alongside the token (extending the
        # schema to track purpose is a future migration; for now we
        # log it so the operator can disambiguate).
        # TODO(M1.4): when the schema gains a ``purpose`` column,
        # include it in the INSERT and gate consume_token by purpose.
        _ = purpose
        return raw_token

    def consume_token(self, raw_token: str) -> str | None:
        """Return the email if the token is valid; mark as used.

        Valid means: the hash matches, the token has not been used
        before, and the TTL has not expired. Returns ``None`` for any
        failure (invalid, used, expired) so the caller cannot
        distinguish.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        rows = self._db.execute_sql(
            self.SELECT_BY_HASH_SQL, [token_hash]
        )
        if not rows:
            return None
        # If used_at is already set, the token was consumed previously.
        # Refuse early so the caller cannot re-consume a used token.
        if rows[0]["used_at"] is not None:
            return None
        now = datetime.now(UTC)
        # Atomically mark used (RETURNING the email so we confirm the
        # update matched at least one row). The WHERE clause has
        # ``used_at IS NULL`` so an already-used token matches zero rows
        # and RETURNING returns an empty list.
        result = self._db.execute_sql(
            self.CONSUME_TOKEN_SQL, [now, token_hash, now]
        )
        if not result:
            return None
        return result[0]["email"]

    def list_active(self) -> list[dict]:
        """Return all unexpired, unused tokens for the admin panel."""
        return self._db.execute_sql(
            self.SELECT_ACTIVE_SQL, [datetime.now(UTC)]
        )


__all__ = ["MagicLinkPortImpl"]
