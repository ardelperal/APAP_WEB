"""Postgres-backed ``MagicLinkPort`` adapter (M1, R1, R3).

The adapter opens an async psycopg connection on first use, runs the
``magic_link_tokens`` DDL once (idempotent), and serves the two port
methods. The transport call is intentionally executed AFTER the database
commit so a transport failure cannot roll back the persisted row — the
user can always request a fresh link, but a transport failure on a
rolled-back row would leave no audit trail at all.

The class follows the same shape as
:class:`app.core.local_backend.db.LocalPostgresExecutor`: ``__init__``
takes a DSN + optional ``search_path``, and a private ``_connect``
opens a connection. The previous-revoke + insert in
:meth:`request_magic_link` runs in a single transaction (one
``UPDATE`` followed by one ``INSERT ... RETURNING``) so the per-email
"only one open token at a time" invariant holds under concurrent
requests.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.core.auth_magic.get_mail_transport import get_mail_transport
from app.core.ports.magic_link_port import MagicLinkRequest
from app.core.ports.mail_transport_port import MailTransport

_UTC = UTC


class DatabaseError(RuntimeError):
    """Connection-level PostgreSQL failure."""


class QueryError(RuntimeError):
    """Query-level failure safe to map to HTTP 4xx.

    Mirrors :class:`app.core.local_backend.db.QueryError` so the
    M0/M1 error vocabulary is consistent; the magic-link adapter does
    not currently translate any specific ``psycopg.errors`` subclass but
    the seam is in place for F2/F3 to do so without renaming.
    """

    def __init__(self, message: str, code: str = "query_error") -> None:
        super().__init__(message)
        self.code = code


#: Location of the DDL file relative to the repo root. The path is
#: resolved at import time so the adapter can be reused from
#: background workers (the lifespan startup path) without a CWD-relative
#: search surprise.
_DDL_FILENAME = "007_create_magic_link_tokens.sql"


def _resolve_ddl_path() -> Path:
    """Return the absolute path of the DDL file.

    The file lives at ``app/core/migrations/sql/00X_create_magic_link_tokens.sql``
    per the M1 spec. The adapter imports this module from
    ``app/core/auth_magic/``, so the relative path is one ``..`` jump
    up (out of ``auth_magic/``) and then sideways into
    ``migrations/sql/`` — both ``auth_magic/`` and ``migrations/`` are
    siblings under ``app/core/``.
    """
    return Path(__file__).resolve().parents[1] / "migrations" / "sql" / _DDL_FILENAME


class PostgresMagicLinkAdapter:
    """Postgres-backed ``MagicLinkPort``.

    The instance is bound to a single DSN (and optional ``search_path``)
    and opens a fresh async connection per logical operation. This is
    consistent with the M0 executor — there is no M0 connection pool and
    the magic-link adapter does not introduce one either. The transport
    is injected so tests can substitute a stub that captures
    ``raw_token`` for round-trip verification.
    """

    def __init__(
        self,
        dsn: str,
        *,
        search_path: str | None = None,
        transport: MailTransport | None = None,
    ) -> None:
        self._dsn = dsn
        self._search_path = search_path
        # The transport is resolved lazily on first ``request_magic_link``
        # call (not at ``__init__``) so that an F1 test that mutates the
        # process env (``monkeypatch.setenv("APAP_SMTP_HOST", ...)``) and
        # then clears ``get_mail_transport.cache_clear()`` sees the new
        # value without having to re-instantiate the adapter.
        self._explicit_transport: MailTransport | None = transport

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        """Open an async connection and apply the optional ``search_path``."""
        connection = await psycopg.AsyncConnection.connect(self._dsn, connect_timeout=5)
        if self._search_path:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT set_config('search_path', %s, false)",
                    (self._search_path,),
                )
            await connection.commit()
        return connection

    async def _ensure_schema(self, connection: psycopg.AsyncConnection[Any]) -> None:
        """Run the DDL once per connection (``CREATE TABLE IF NOT EXISTS``).

        The file is read at call time (not import time) so a deployment
        that overwrites the SQL file before a process restart picks up
        the new DDL on first use. ``cursor.execute`` accepts the full
        multi-statement string because the DDL is two
        ``CREATE ... IF NOT EXISTS`` statements; psycopg's client cursor
        sends them in a single Parse/Bind/Execute round-trip with the
        server's simple-query protocol path.
        """
        ddl_path = _resolve_ddl_path()
        sql_text = ddl_path.read_text(encoding="utf-8")
        async with connection.cursor() as cursor:
            await cursor.execute(sql_text)
        await connection.commit()

    async def request_magic_link(
        self, email: str, *, ttl_seconds: int = 86400
    ) -> MagicLinkRequest:
        """Persist a new request and emit the raw token via the transport."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        transport = self._explicit_transport or get_mail_transport()
        async with await self._connect() as connection:
            await self._ensure_schema(connection)
            # 1) Revoke any previous unconsumed token for the same email
            #    in the same transaction. Setting ``consumed_at`` to the
            #    row's own ``requested_at`` keeps the audit trail honest
            #    (the new request's time, not the revoke wall-clock) — we
            #    use ``now()`` for simplicity and idempotency: the row is
            #    no longer in the "open" partial-index set, which is all
            #    the contract requires.
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE magic_link_tokens "
                    "SET consumed_at = now() "
                    "WHERE email = %s AND consumed_at IS NULL",
                    (email,),
                )
                # 2) Insert the new row and read it back in one round-trip.
                #    ``RETURNING`` carries the server-assigned
                #    ``requested_at`` so the ``MagicLinkRequest`` we build
                #    below reflects the database time, not the client
                #    wall-clock.
                await cursor.execute(
                    "INSERT INTO magic_link_tokens "
                    "(email, token_hash, expires_at) "
                    "VALUES (%s, %s, now() + make_interval(secs => %s)) "
                    "RETURNING email, token_hash, requested_at, "
                    "expires_at, consumed_at",
                    (email, token_hash, ttl_seconds),
                )
                row = await cursor.fetchone()
            await connection.commit()

        if row is None:
            # Should be unreachable — the INSERT always returns one row —
            # but the type-checker needs the assertion.
            raise QueryError("INSERT RETURNING produced no row")

        # The transport call runs AFTER the commit so a transport
        # failure does not roll back the persisted row. The ``base_url``
        # is left as an empty string for F1: the transport builds the
        # verify URL with whatever value the caller passed in. F2 will
        # inject ``settings.app_base_url`` at the route layer.
        verify_url = self._transport_build_verify_url("", raw_token)
        await transport.send_magic_link(email, raw_token, "")

        return MagicLinkRequest(
            email=row[0],
            token_hash=row[1],
            requested_at=_as_utc(row[2]),
            expires_at=_as_utc(row[3]),
            consumed_at=_as_utc(row[4]) if row[4] is not None else None,
            transport_payload={"verify_url": verify_url, "raw_token": raw_token},
        )

    async def consume_magic_link(self, token_hash: str) -> str | None:
        """Atomically consume ``token_hash`` and return the email, or ``None``.

        The single ``UPDATE ... RETURNING email`` statement is the
        atomicity boundary: the row is marked consumed at the same
        instant the email is returned, so a second call for the same
        ``token_hash`` (or a call for an expired token) sees zero rows
        and returns ``None``.
        """
        async with await self._connect() as connection:
            await self._ensure_schema(connection)
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "UPDATE magic_link_tokens "
                    "SET consumed_at = now() "
                    "WHERE token_hash = %s "
                    "AND consumed_at IS NULL "
                    "AND expires_at > now() "
                    "RETURNING email",
                    (token_hash,),
                )
                row = await cursor.fetchone()
            await connection.commit()
        if row is None:
            return None
        return row[0]

    @staticmethod
    def _transport_build_verify_url(base_url: str, raw_token: str) -> str:
        """Build the verify URL the same way the transport does.

        Centralised here so the value stored in ``transport_payload`` and
        the value the transport appends to ``mailbox.jsonl`` are
        byte-identical (tests assert on the URL shape).
        """
        return f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}"


def _as_utc(value: datetime) -> datetime:
    """Coerce a psycopg-returned ``datetime`` to a UTC-aware ``datetime``.

    psycopg returns ``TIMESTAMPTZ`` columns as timezone-aware
    ``datetime`` values in UTC; the conversion is a no-op for those.
    For naive values (which should not occur for the DDL we issue, but
    which psycopg may pass through in test scenarios) we attach UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC)


__all__ = ["DatabaseError", "PostgresMagicLinkAdapter", "QueryError"]
