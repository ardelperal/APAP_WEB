"""Process-scoped resolver for the ``MailTransport`` (M1, M3).

The resolver picks between :class:`ConsoleMailTransport` (the default
for dev and CI) and :class:`SMTPMailTransport` (the M3 production
transport that requires ``APAP_SMTP_HOST``) based on a single env var.
The result is cached with :func:`functools.lru_cache` for the lifetime
of the process — flipping the env var requires a restart (or an
explicit ``get_mail_transport.cache_clear()`` from a test).

The cache lives at the module level (not as a default-argument closure)
so the FastAPI lifespan startup and the F1 integration tests can call
``get_mail_transport.cache_clear()`` to pick up env mutations without
holding a reference to the wrapper function.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from app.core.auth_magic.mail_transports import (
    ConsoleMailTransport,
    SMTPMailTransport,
)
from app.core.ports.mail_transport_port import MailTransport


@lru_cache(maxsize=1)
def get_mail_transport() -> MailTransport:
    """Return the singleton :class:`MailTransport` for this process.

    When ``APAP_SMTP_HOST`` is set and non-empty, returns an
    :class:`SMTPMailTransport` configured from
    ``APAP_SMTP_HOST`` / ``APAP_SMTP_PORT`` (default 587) /
    ``APAP_SMTP_USER`` (default empty = no auth) /
    ``APAP_SMTP_PASSWORD`` (default empty = no auth) /
    ``APAP_SMTP_FROM`` (default ``noreply@apap.local``).
    Otherwise returns a :class:`ConsoleMailTransport` that writes to
    ``tests/mailbox.jsonl`` (resolved against the project root).

    The cache is process-scoped; tests that mutate ``APAP_SMTP_HOST``
    must call ``get_mail_transport.cache_clear()`` before the next
    ``get_mail_transport()`` call to observe the new value.
    """
    if os.environ.get("APAP_SMTP_HOST"):
        return SMTPMailTransport(
            host=os.environ.get("APAP_SMTP_HOST", ""),
            port=int(os.environ.get("APAP_SMTP_PORT", "587")),
            user=os.environ.get("APAP_SMTP_USER", ""),
            password=os.environ.get("APAP_SMTP_PASSWORD", ""),
            from_addr=os.environ.get("APAP_SMTP_FROM", "noreply@apap.local"),
        )
    return ConsoleMailTransport()


__all__ = ["get_mail_transport"]


# Silence the unused-import warning for ``Path`` — the resolver does
# not currently accept a path override (the ``ConsoleMailTransport``
# resolves its own default), but the symbol is part of the public
# surface for F3's verifier and for future custom-path test fixtures.
_ = Path
