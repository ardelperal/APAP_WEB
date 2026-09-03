"""Mail transport implementations for the magic-link self-host slice (M1, R2).

Two implementations live here:

- :class:`ConsoleMailTransport` — the default for dev and CI. It appends
  one JSON line to ``tests/mailbox.jsonl`` per ``send_magic_link`` call
  so the verify URL is observable end-to-end without any SMTP
  infrastructure. The mailbox file is read by the F3
  ``check_magic_link_local_round_trip`` gate to extract the verify URL
  the route just emitted.

- :class:`SMTPMailTransport` — the M1.1 placeholder. The class is in
  place so the resolver at ``app.core.auth_magic.get_mail_transport``
  has a concrete symbol to return when ``APAP_SMTP_HOST`` is set, but
  every ``send_magic_link`` call raises :class:`NotImplementedError`.
  The M1.1 wiring will replace the raise with an ``asyncio.to_thread``
  call to ``smtplib.SMTP`` with a ``MIMEText`` message.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

#: Path of the JSONL mailbox, relative to the repo root. The default
#: constructor argument for :class:`ConsoleMailTransport` resolves
#: this against the project root (the parent of ``app/``) so the
#: verifier in F3 can read the same file the test wrote.
DEFAULT_MAILBOX_PATH = pathlib.Path("tests") / "mailbox.jsonl"


class ConsoleMailTransport:
    """Dev/CI transport that writes one JSON line per call (spec R2).

    Each ``send_magic_link`` call appends a single line to the mailbox
    file with the keys ``{event, email, sent_at, verify_url, raw_token}``.
    The file write is offloaded to a worker thread via
    :func:`asyncio.to_thread` because the FastAPI request loop is
    single-threaded and the file I/O must not block the event loop.
    """

    def __init__(self, mailbox_path: pathlib.Path | None = None) -> None:
        if mailbox_path is None:
            # ``parents[3]`` lands at the repo root (parent of ``app/``),
            # where ``tests/`` is a sibling of ``app/``. This matches the
            # F3 verifier's read path (``tests/mailbox.jsonl``).
            mailbox_path = (
                pathlib.Path(__file__).resolve().parents[3]
                / DEFAULT_MAILBOX_PATH
            )
        self._path = mailbox_path

    @property
    def path(self) -> pathlib.Path:
        """Absolute path of the JSONL mailbox file."""
        return self._path

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        """Append one JSON line to the mailbox and return."""
        verify_url = self._build_verify_url(base_url, raw_token)
        payload: dict[str, Any] = {
            "event": "magic_link.sent",
            "email": email,
            "sent_at": _utcnow_iso(),
            "verify_url": verify_url,
            "raw_token": raw_token,
        }
        await asyncio.to_thread(self._append_sync, payload)

    @staticmethod
    def _build_verify_url(base_url: str, raw_token: str) -> str:
        """Build the verify URL (spec R5 shape)."""
        return f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}"

    def _append_sync(self, payload: dict[str, Any]) -> None:
        """Blocking append — run via :func:`asyncio.to_thread` from the caller."""
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class SMTPMailTransport:
    """Placeholder for the M1.1 SMTP-backed transport (spec R2).

    M1 wires this through the resolver at
    :mod:`app.core.auth_magic.get_mail_transport` so flipping
    ``APAP_SMTP_HOST`` selects it, but the actual SMTP send is out of
    scope. Every call raises :class:`NotImplementedError` so a missing
    M1.1 implementation surfaces as a clear runtime error rather than a
    silent no-op.

    The M1.1 wiring contract:

    - Read ``APAP_SMTP_HOST``, ``APAP_SMTP_PORT`` (default 587),
      ``APAP_SMTP_USERNAME``, ``APAP_SMTP_PASSWORD``,
      ``APAP_SMTP_FROM`` (default ``noreply@apap.local``),
      ``APAP_SMTP_USE_TLS`` (default true) at ``__init__`` time.
    - Build an :class:`email.message.EmailMessage` with a plain-text
      body that contains the ``verify_url`` and a short greeting.
    - Open ``smtplib.SMTP(host, port)`` in a worker thread via
      :func:`asyncio.to_thread` (the event loop must not block on
      I/O). If ``APAP_SMTP_USE_TLS`` is true, call ``starttls()`` and
      ``login(username, password)`` before ``send_message(msg)``.
    - Treat ``SMTPException`` as a transport failure (do NOT roll back
      the magic-link row in the database — the persisted row IS the
      audit trail).
    """

    def __init__(self) -> None:
        # M1.1 will read the env vars here and cache the SMTP client
        # parameters. For M1 the constructor is a no-op so the symbol
        # can be resolved by the resolver without side effects.
        return

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        """Placeholder — raises :class:`NotImplementedError`.

        The M1.1 implementation will replace this method with a real
        SMTP send (see the class docstring for the contract).
        """
        raise NotImplementedError(
            "SMTPMailTransport is the M1.1 wiring placeholder. "
            "Configure APAP_SMTP_HOST to enable."
        )


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``+00:00``."""
    return datetime.now(tz=UTC).isoformat()


#: Type-checker helper: the M1.1 implementation will type its message
#: variable as ``EmailMessage``; the import is in the module namespace
#: so a future M1.1 PR can use it without a new import.
_ = EmailMessage
