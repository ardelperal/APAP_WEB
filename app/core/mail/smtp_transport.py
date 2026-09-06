"""SMTP transport for the local backend (M3.4 magic-link wiring, issue #651).

Reads its config from the :class:`Settings` singleton
(``APAP_SMTP_HOST/PORT/USER/PASSWORD/FROM``) and sends an email via
``smtplib``. The route layer at
:mod:`app.core.local_backend.magic_link` calls :meth:`SMTPMailTransport.send`
after :meth:`MagicLinkPortImpl.create_token` mints a raw token.

The transport is a no-op when ``smtp_host`` is unset (the local dev
path): the magic-link route still mints the token so the round-trip
test can assert against the MailDev HTTP API in CI; the user just
never receives the email locally. When ``smtp_host`` is set, the
transport opens a TLS connection (``SMTP_SSL`` on port 465, Resend's
default) and sends the message.

Surfacing failures
-----------------

``smtplib.SMTPException`` and any socket error raised during
``sendmail`` are translated to :class:`SMTPTransportError` so the
route can map to HTTP 5xx without leaking the SMTP transport shape
into the application layer.

Hard rules (web-tdd-philosophy):

- Rule 4 (no humo): unit tests assert the envelope (``From``/``To``/
  ``Subject``), the port (465 vs 587), and the error mapping — never
  absence-of-error.
- Rule 8 (no production mutation): ``smtplib`` is patched in tests;
  the real SMTP server is never contacted.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol


class SMTPTransportError(RuntimeError):
    """Raised when ``smtplib.sendmail`` (or a socket operation during
    ``connect``/``starttls``) fails.

    The route layer maps this to HTTP 5xx; the original ``smtplib``
    error is preserved as ``__cause__``.
    """


class _SettingsLike(Protocol):
    """The fields the transport reads from the settings singleton.

    A Protocol (not the concrete ``Settings`` class) keeps this module
    free of the config import cycle: the magic-link route imports
    ``Settings`` for DI; the transport only needs the SMTP slice.
    """

    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str


class SMTPMailTransport:
    """Thin ``smtplib`` wrapper for the magic-link email channel.

    Constructed once at lifespan startup and stored on ``app.state``
    so the magic-link route can reach it via ``request.app.state``.

    The transport never raises on construction: an unset
    ``smtp_host`` simply turns the transport into a no-op (the local
    dev path). ``send`` raises :class:`SMTPTransportError` only when
    SMTP is configured AND ``smtplib`` fails.
    """

    def __init__(self, settings: _SettingsLike) -> None:
        self._settings = settings

    def send(self, to_addr: str, subject: str, body: str) -> bool:
        """Send ``body`` to ``to_addr`` with the given ``subject``.

        Returns ``False`` when ``smtp_host`` is unset (local dev path:
        the magic-link route still mints the token, but no email is
        sent). Returns ``True`` on success. Raises
        :class:`SMTPTransportError` on transport failure so the route
        can map to HTTP 5xx.
        """
        if not self._settings.smtp_host:
            # No-op path: the local dev workflow reads the message
            # back from MailDev's HTTP API (or, when no SMTP is
            # configured at all, via direct token inspection in the
            # admin panel). The route never knows the difference.
            return False

        msg = EmailMessage()
        msg["From"] = self._settings.smtp_from
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            if self._settings.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    host=self._settings.smtp_host,
                    port=self._settings.smtp_port,
                ) as client:
                    client.login(self._settings.smtp_user, self._settings.smtp_password)
                    client.send_message(msg)
            else:
                with smtplib.SMTP(
                    host=self._settings.smtp_host,
                    port=self._settings.smtp_port,
                ) as client:
                    client.starttls()
                    client.login(self._settings.smtp_user, self._settings.smtp_password)
                    client.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise SMTPTransportError(f"SMTP send failed: {exc}") from exc
        return True


__all__ = ["SMTPMailTransport", "SMTPTransportError"]
