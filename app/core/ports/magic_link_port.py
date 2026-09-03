"""Protocol contract for magic-link persistence and consumption (M1, R1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MagicLinkRequest:
    """The persisted shape of one magic-link request (spec R1).

    ``token_hash`` is the SHA-256 hex digest of the raw token that was sent
    to the user — the raw token itself is never persisted. ``transport_payload``
    carries the runtime data the transport needs to deliver the link
    (currently just the verify URL, but extensible).
    """

    email: str
    token_hash: str
    requested_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    transport_payload: dict[str, object]


@runtime_checkable
class MagicLinkPort(Protocol):
    """Backend-agnostic interface for magic-link persistence (spec R1)."""

    async def request_magic_link(
        self, email: str, *, ttl_seconds: int = 86400
    ) -> MagicLinkRequest:
        """Persist a new magic-link request for ``email``.

        Hashes the raw token via ``sha256(token).hexdigest()`` BEFORE
        persisting; only the hash ever lands in the table. Revokes any
        previous unconsumed token for the same email in the same
        transaction. Emits the raw token to the injected
        :class:`MailTransport` AFTER the commit (transport failures must
        not roll back the persistence).
        """
        ...

    async def consume_magic_link(self, token_hash: str) -> str | None:
        """Atomically consume ``token_hash`` and return the authorised email.

        Returns the email if the row exists, is unconsumed, and is not
        expired. Returns ``None`` otherwise (expired, already consumed, or
        unknown token). The single-statement ``UPDATE ... RETURNING email``
        is the atomicity boundary; the caller can rely on the result
        without a follow-up SELECT.
        """
        ...
