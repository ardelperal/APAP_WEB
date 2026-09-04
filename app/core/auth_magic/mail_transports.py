"""Mail transport implementations for the magic-link self-host slice (M1, M3).

Three implementations live here:

- :class:`ConsoleMailTransport` — the default for dev and CI. It appends
  one JSON line to ``tests/mailbox.jsonl`` per ``send_magic_link`` call
  so the verify URL is observable end-to-end without any SMTP
  infrastructure. The mailbox file is read by the F3
  ``check_magic_link_local_round_trip`` gate to extract the verify URL
  the route just emitted.

- :class:`SMTPMailTransport` — the M3 production transport. Connects to
  the SMTP relay configured via ``APAP_SMTP_HOST`` (see
  :mod:`app.core.auth_magic.get_mail_transport`) and sends a plain-text
  message containing the verify URL. Synchronous I/O is offloaded to a
  worker thread via :func:`asyncio.to_thread`.

- :class:`SMTPTransportError` — :class:`RuntimeError` subclass raised by
  :class:`SMTPMailTransport` on SMTP-level failures. The F2 routes map
  this to a 5xx response (the existing ``RuntimeError`` branch in the
  route handler covers it).
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from email.mime.text import MIMEText
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


class SMTPTransportError(RuntimeError):
    """Raised when the SMTP transport cannot deliver a magic-link message.

    Subclass of ``RuntimeError`` so the existing F2 magic-link routes
    can map the failure to a 5xx response without introducing a new
    exception-handling branch. Callers can still distinguish
    ``SMTPTransportError`` from other runtime errors via ``isinstance``.
    """


class SMTPMailTransport:
    """Send magic-link emails via stdlib :mod:`smtplib` (M3, R1).

    The transport reads SMTP configuration from the constructor
    arguments (which the resolver
    :func:`app.core.auth_magic.get_mail_transport` populates from
    ``APAP_SMTP_HOST`` / ``APAP_SMTP_PORT`` / ``APAP_SMTP_USER`` /
    ``APAP_SMTP_PASSWORD`` / ``APAP_SMTP_FROM``). Synchronous I/O is
    offloaded to a worker thread via :func:`asyncio.to_thread` so the
    FastAPI event loop never blocks on SMTP socket reads.

    TLS handling: when ``port == 465`` the transport uses
    :class:`smtplib.SMTP_SSL` (implicit TLS). For ``port == 587`` with
    ``user`` non-empty, the transport calls ``starttls()`` after
    ``ehlo()`` so the AUTH LOGIN handshake is encrypted. For
    unauthenticated relays (``user == ""``), the transport connects in
    plaintext on port 25 / 587 (acceptable for local-dev MailPit and CI
    sandboxes; production deployments should always set
    ``APAP_SMTP_USER``).

    Failures are translated to :class:`SMTPTransportError` so the F2
    routes can map the failure to a 5xx response without introducing a
    new exception-handling branch.
    """

    def __init__(
        self,
        host: str,
        port: int = 587,
        user: str = "",
        password: str = "",
        from_addr: str = "noreply@apap.local",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_addr = from_addr

    async def send_magic_link(
        self, email: str, raw_token: str, base_url: str
    ) -> None:
        """Build a plain-text verify-URL message and send via SMTP."""
        verify_url = self._build_verify_url(base_url, raw_token)
        subject = "APAP_WEB — inicia sesión"
        body = (
            f"APAP_WEB — inicia sesión\n\n"
            f"Abre este enlace en los próximos 24 horas para iniciar sesión:\n\n"
            f"  {verify_url}\n\n"
            f"Si no solicitaste este correo, ignóralo.\n"
        )
        msg = MIMEText(body, _subtype="plain", _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = email
        try:
            await asyncio.to_thread(
                self._send_sync, email, msg.as_string()
            )
        except smtplib.SMTPException as exc:
            raise SMTPTransportError(
                f"SMTP delivery failed: {exc}"
            ) from exc

    @staticmethod
    def _build_verify_url(base_url: str, raw_token: str) -> str:
        """Build the verify URL (spec R1 shape)."""
        return f"{base_url.rstrip('/')}/auth/magic/verify?token={raw_token}"

    def _send_sync(self, to_addr: str, msg_str: str) -> None:
        """Open the SMTP connection, send ``msg_str``, close (in thread)."""
        if self._port == 465:
            client = smtplib.SMTP_SSL(self._host, self._port, timeout=10)
        else:
            client = smtplib.SMTP(self._host, self._port, timeout=10)
        try:
            client.ehlo()
            if self._user and self._port != 465:
                client.starttls()
                client.ehlo()
            if self._user:
                client.login(self._user, self._password)
            client.sendmail(self._from_addr, [to_addr], msg_str)
        finally:
            try:
                client.quit()
            except smtplib.SMTPException:
                pass


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``+00:00``."""
    return datetime.now(tz=UTC).isoformat()


#: Type-checker helper: the M3 implementation types its message
#: variable as ``EmailMessage``; the import is kept in the module namespace
#: so future helper code can use it without a new import.
_ = EmailMessage
