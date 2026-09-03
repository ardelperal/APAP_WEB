"""Integration tests for the M1 magic-link foundation (F1 acceptance).

The seven atoms cover the F1 contract:

1. The adapter persists a row whose ``token_hash`` matches
   ``sha256(raw_token).hexdigest()`` (spec R1, R3).
2. ``consume_magic_link`` returns the email on first use.
3. ``consume_magic_link`` returns ``None`` on second use (atomic
   single-statement ``UPDATE ... RETURNING email``).
4. ``consume_magic_link`` returns ``None`` after expiry
   (``expires_at <= now()``).
5. :class:`ConsoleMailTransport` writes one JSON line per call to
   ``tests/mailbox.jsonl`` with the spec R2 shape.
6. :func:`get_mail_transport` returns the console transport when
   ``APAP_SMTP_HOST`` is unset.
7. The Postgres adapter round-trips a full request + consume against
   an ephemeral schema (proves the DDL + adapter + transport wire).

The test file uses the session-scoped ``ephemeral_postgres`` fixture
from :mod:`tests.integration.conftest`, which provisions a fresh
``int_test_<uuid>`` schema per test session and truncates all tables
between tests. The magic-link table is created by the adapter's
``_ensure_schema`` on the first ``request_magic_link`` / ``consume``
call, so the test owns DDL ordering.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.auth_magic.get_mail_transport import get_mail_transport
from app.core.auth_magic.mail_transports import (
    ConsoleMailTransport,
    SMTPMailTransport,
)
from app.core.auth_magic.postgres_adapter import PostgresMagicLinkAdapter
from app.core.ports.magic_link_port import MagicLinkRequest
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Transport stubs
# ---------------------------------------------------------------------------


class _CapturingTransport:
    """Test transport that records every ``send_magic_link`` invocation.

    The adapter returns the ``raw_token`` in the ``transport_payload``
    dict, but F1 asserts on the transport's view of the token (so the
    adapter and the transport are validated independently, catching
    any mismatch in the verify URL construction).
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        self.sent.append(
            {
                "email": email,
                "raw_token": raw_token,
                "base_url": base_url,
                "verify_url": f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}",
            }
        )


# ---------------------------------------------------------------------------
# 1. request_magic_link persists row with correct hash
# ---------------------------------------------------------------------------


async def test_request_magic_link_persists_row_with_correct_hash(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Adapter hashes the raw token before persisting (spec R1, R3)."""
    transport = _CapturingTransport()
    adapter = PostgresMagicLinkAdapter(
        ephemeral_postgres.dsn,
        search_path=ephemeral_postgres.schema,
        transport=transport,
    )

    request = await adapter.request_magic_link("user@apap.local")

    # Adapter-side: the request carries the SHA-256 of the raw token.
    expected_hash = hashlib.sha256(
        request.transport_payload["raw_token"].encode("utf-8")
    ).hexdigest()
    assert request.token_hash == expected_hash

    # Transport-side: the raw token reached the transport (not the hash).
    assert len(transport.sent) == 1
    assert transport.sent[0]["email"] == "user@apap.local"
    assert transport.sent[0]["raw_token"] == request.transport_payload["raw_token"]
    # The hash must NOT leak to the transport.
    assert transport.sent[0]["raw_token"] != request.token_hash

    # DB-side: read the persisted row and verify the stored hash.
    rows = ephemeral_postgres.execute(
        "SELECT email, token_hash FROM magic_link_tokens"
    )
    assert len(rows) == 1
    assert rows[0]["email"] == "user@apap.local"
    assert rows[0]["token_hash"] == expected_hash


# ---------------------------------------------------------------------------
# 2. consume_magic_link returns email on first use
# ---------------------------------------------------------------------------


async def test_consume_magic_link_returns_email_on_first_use(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """A fresh token resolves to its authorised email (spec R1)."""
    transport = _CapturingTransport()
    adapter = PostgresMagicLinkAdapter(
        ephemeral_postgres.dsn,
        search_path=ephemeral_postgres.schema,
        transport=transport,
    )

    request = await adapter.request_magic_link("first@apap.local")
    email = await adapter.consume_magic_link(request.token_hash)
    assert email == "first@apap.local"

    # The row's consumed_at must now be set.
    rows = ephemeral_postgres.execute(
        "SELECT consumed_at FROM magic_link_tokens WHERE token_hash = %s",
        [request.token_hash],
    )
    assert len(rows) == 1
    assert rows[0]["consumed_at"] is not None


# ---------------------------------------------------------------------------
# 3. consume_magic_link returns None on reuse
# ---------------------------------------------------------------------------


async def test_consume_magic_link_returns_none_on_reuse(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """A second consume of the same token returns ``None`` (spec R1)."""
    transport = _CapturingTransport()
    adapter = PostgresMagicLinkAdapter(
        ephemeral_postgres.dsn,
        search_path=ephemeral_postgres.schema,
        transport=transport,
    )

    request = await adapter.request_magic_link("reuse@apap.local")
    first = await adapter.consume_magic_link(request.token_hash)
    second = await adapter.consume_magic_link(request.token_hash)
    assert first == "reuse@apap.local"
    assert second is None


# ---------------------------------------------------------------------------
# 4. consume_magic_link returns None after expiry
# ---------------------------------------------------------------------------


async def test_consume_magic_link_returns_none_after_expiry(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """An expired token cannot be consumed (spec R1)."""
    transport = _CapturingTransport()
    adapter = PostgresMagicLinkAdapter(
        ephemeral_postgres.dsn,
        search_path=ephemeral_postgres.schema,
        transport=transport,
    )

    # ``ttl_seconds=0`` means ``expires_at = requested_at`` (both server
    # ``now()``); the consume path requires ``expires_at > now()`` so the
    # call must return ``None`` even on the first try.
    request = await adapter.request_magic_link("expiry@apap.local", ttl_seconds=0)
    assert request.expires_at <= datetime.now(tz=UTC)
    email = await adapter.consume_magic_link(request.token_hash)
    assert email is None


# ---------------------------------------------------------------------------
# 5. ConsoleMailTransport appends one JSON line
# ---------------------------------------------------------------------------


async def test_console_mail_transport_appends_json_line(tmp_path: Path) -> None:
    """The console transport writes one JSON line per send (spec R2)."""
    mailbox = tmp_path / "mailbox.jsonl"
    transport = ConsoleMailTransport(mailbox_path=mailbox)

    await transport.send_magic_link("console@apap.local", "raw-token-abc", "https://app.example.test")

    assert mailbox.exists()
    contents = mailbox.read_text(encoding="utf-8")
    lines = [line for line in contents.split("\n") if line]
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["event"] == "magic_link.sent"
    assert payload["email"] == "console@apap.local"
    assert payload["raw_token"] == "raw-token-abc"
    assert payload["verify_url"] == (
        "https://app.example.test/auth/magic/verify?token=raw-token-abc"
    )
    # ``sent_at`` must be a parseable ISO-8601 timestamp.
    sent_at = datetime.fromisoformat(payload["sent_at"])
    assert sent_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 6. get_mail_transport returns console when APAP_SMTP_HOST is unset
# ---------------------------------------------------------------------------


async def test_get_mail_transport_returns_console_when_no_smtp_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``APAP_SMTP_HOST`` the resolver returns the console transport."""
    monkeypatch.delenv("APAP_SMTP_HOST", raising=False)
    # ``lru_cache`` is module-scoped; clear it so the test sees the
    # current env state rather than a cached result from an earlier
    # test in the session.
    get_mail_transport.cache_clear()
    try:
        transport = get_mail_transport()
    finally:
        get_mail_transport.cache_clear()

    assert isinstance(transport, ConsoleMailTransport)
    assert not isinstance(transport, SMTPMailTransport)


# ---------------------------------------------------------------------------
# 7. Postgres adapter round-trip with ephemeral schema
# ---------------------------------------------------------------------------


async def test_postgres_adapter_roundtrip_with_ephemeral_schema(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Full request + consume round-trip against a real Postgres schema."""
    transport = _CapturingTransport()
    adapter = PostgresMagicLinkAdapter(
        ephemeral_postgres.dsn,
        search_path=ephemeral_postgres.schema,
        transport=transport,
    )

    request = await adapter.request_magic_link("roundtrip@apap.local")

    # Row count + hash equality.
    rows = ephemeral_postgres.execute(
        "SELECT email, token_hash FROM magic_link_tokens"
    )
    assert len(rows) == 1
    assert rows[0]["token_hash"] == request.token_hash

    # ``transport_payload`` shape: the contract is
    # ``{verify_url, raw_token}`` so the F2 route layer can build the
    # cookie + redirect without re-deriving the URL.
    assert set(request.transport_payload) == {"verify_url", "raw_token"}
    assert request.transport_payload["raw_token"] == transport.sent[0]["raw_token"]
    assert (
        request.transport_payload["verify_url"]
        == transport.sent[0]["verify_url"]
    )

    # The MagicLinkRequest dataclass shape matches the spec.
    assert isinstance(request, MagicLinkRequest)
    assert request.email == "roundtrip@apap.local"
    assert request.consumed_at is None

    # Consume completes the round-trip.
    consumed_email = await adapter.consume_magic_link(request.token_hash)
    assert consumed_email == "roundtrip@apap.local"
