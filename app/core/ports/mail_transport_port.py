"""Protocol contract for email delivery (M1, R2)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MailTransport(Protocol):
    """Backend-agnostic interface for outbound magic-link email (spec R2)."""

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        """Build the verification URL and deliver it to ``email``.

        The URL shape is fixed by spec R5:
        ``f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}"``.
        The transport is the only place where the raw token lives in
        clear text outside the database; it MUST be delivered through a
        path that does not log or persist the token beyond the verify URL.
        """
        ...
