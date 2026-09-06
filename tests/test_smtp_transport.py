"""Unit tests for :class:`SMTPMailTransport` (M3.4 magic-link wiring).

The transport reads its config from ``APAP_SMTP_*`` env vars on the
:class:`Settings` singleton, opens an ``smtplib`` connection, sends
the message, and surfaces transport-level failures as
:class:`SMTPTransportError` (the route layer maps that to HTTP 5xx).

Hard rules honoured (apap-testing):

- HR-10 (no real I/O): ``smtplib.SMTP_SSL`` / ``SMTP`` are patched
  with a fake whose ``sendmail`` / ``quit`` calls are recorded but
  never reach the network.
- HR-6 / HR-12 (deterministic, no flakiness): the tests do not depend
  on the order of dict keys, on timezone, or on real SMTP servers.

The integration coverage for the route that *uses* the transport lives
at ``tests/integration/test_magic_link_routes.py`` (real Postgres +
mocked SMTP transport); these unit tests pin the transport class in
isolation.
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from app.core.config import Settings

import pytest

from app.core.mail.smtp_transport import (
    SMTPMailTransport,
    SMTPTransportError,
)

# --- helpers --------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    """Build a ``Settings`` instance with the SMTP fields populated.

    The transport only reads ``smtp_host``, ``smtp_port``, ``smtp_user``,
    ``smtp_password``, ``smtp_from``; we pass a real ``Settings`` so
    pydantic validation runs (catches typos in env var names).
    """
    from app.core.config import Settings

    base: dict[str, object] = {
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "debug": True,  # bypass secret validation
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakeSMTP:
    """Minimal stand-in for ``smtplib.SMTP`` / ``SMTP_SSL``.

    Records the ``send_message`` call so the test asserts the
    envelope and the payload. ``login`` / ``quit`` / ``starttls`` are
    no-ops so the ``with`` block exits cleanly.
    """

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.host: str | None = None
        self.port: int | None = None

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:  # noqa: ARG002
        return None

    def starttls(self) -> None:
        return None

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)

    def quit(self) -> None:
        return None


def _patched_smtp_factory(fake: _FakeSMTP) -> object:
    """Return a side_effect that returns ``fake`` for both ``SMTP_SSL``
    and ``SMTP`` so the test exercises whichever branch the transport
    takes (SSL on 465 vs STARTTLS on 587)."""

    def factory(*args: object, **kwargs: object) -> _FakeSMTP:
        host = kwargs.get("host") or (args[0] if args else None)
        port = kwargs.get("port") or (args[1] if len(args) > 1 else None)
        # mypy: the SMTP constructor signature is ``(host, port)``; we
        # narrow ``object`` to the declared types after the assignment.
        assert isinstance(host, str) or host is None
        assert isinstance(port, int) or port is None
        fake.host = host
        fake.port = port
        return fake

    return factory


# --- SMTPMailTransport ----------------------------------------------------


class TestSMTPMailTransport:
    """The transport is a thin wrapper around ``smtplib``; the tests
    pin the contract that the magic-link route relies on."""

    def test_is_noop_when_smtp_host_unset(self) -> None:
        """Without ``APAP_SMTP_HOST`` the transport does nothing — the
        local dev path. Returns ``False`` so callers know the message
        was *not* sent (vs. raised-on-failure)."""
        transport = SMTPMailTransport(_settings())
        assert transport.send("ana@test.com", "subject", "body") is False

    def test_does_not_call_smtplib_when_noop(self) -> None:
        transport = SMTPMailTransport(_settings())
        with patch("app.core.mail.smtp_transport.smtplib.SMTP_SSL") as smtpssl:
            with patch("app.core.mail.smtp_transport.smtplib.SMTP") as smtp:
                # No return value to assert; just verify the call returns
                # without raising (the no-op branch).
                transport.send("ana@test.com", "subject", "body")
        smtpssl.assert_not_called()
        smtp.assert_not_called()

    def test_uses_smtp_ssl_on_port_465(self) -> None:
        """Resend ships port 465; the transport uses ``SMTP_SSL``."""
        fake = _FakeSMTP()
        transport = SMTPMailTransport(
            _settings(
                smtp_host="smtp.resend.com",
                smtp_port=465,
                smtp_user="resend",
                smtp_password="re_secret",
                smtp_from="onboarding@resend.dev",
            )
        )
        with patch(
            "app.core.mail.smtp_transport.smtplib.SMTP_SSL",
            side_effect=_patched_smtp_factory(fake),
        ):
            transport.send("ana@test.com", "Enlace APAP", "Click aquí.")
        assert fake.host == "smtp.resend.com"
        assert fake.port == 465
        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg["From"] == "onboarding@resend.dev"
        assert msg["To"] == "ana@test.com"
        assert msg["Subject"] == "Enlace APAP"
        body = msg.get_content()
        assert "Click aquí." in body

    def test_uses_starttls_on_port_587(self) -> None:
        """Fallback for non-SSL SMTP servers: STARTTLS via ``SMTP``
        + ``starttls()``."""
        captured: dict[str, object] = {"starttls_called": False}

        class _SmtpWithStarttls(_FakeSMTP):
            def starttls(self) -> None:
                captured["starttls_called"] = True

        def factory(*args: object, **kwargs: object) -> _SmtpWithStarttls:
            inst = _SmtpWithStarttls()
            host = kwargs.get("host") or (args[0] if args else None)
            port = kwargs.get("port") or (args[1] if len(args) > 1 else None)
            assert isinstance(host, str) or host is None
            assert isinstance(port, int) or port is None
            inst.host = host
            inst.port = port
            return inst

        transport = SMTPMailTransport(
            _settings(
                smtp_host="mail.example.com",
                smtp_port=587,
                smtp_user="apap",
                smtp_password="pw",
                smtp_from="apap@example.com",
            )
        )
        with patch(
            "app.core.mail.smtp_transport.smtplib.SMTP",
            side_effect=factory,
        ):
            transport.send("ana@test.com", "Hola", "Body")
        assert captured["starttls_called"] is True
        # The fake returned by ``factory`` carries host/port on the
        # instance itself; we re-derive from the SMTP connection the
        # transport opened by patching the factory's return.
        # (The test above covers the SSL branch where ``_patched_smtp_factory``
        # records host/port; here we only assert the STARTTLS branch fires.)

    def test_raises_smtp_transport_error_on_sendmail_failure(self) -> None:
        """When ``smtplib.SMTP_SSL.send_message`` raises, the transport
        surfaces a :class:`SMTPTransportError` so the route can map
        to HTTP 5xx."""
        class _FailingSMTP(_FakeSMTP):
            def send_message(self, msg: EmailMessage) -> None:
                raise OSError("connection reset")

        def failing_factory(*args: object, **kwargs: object) -> _FailingSMTP:
            return _FailingSMTP()

        transport = SMTPMailTransport(
            _settings(
                smtp_host="smtp.resend.com",
                smtp_port=465,
                smtp_user="resend",
                smtp_password="secret",
                smtp_from="onboarding@resend.dev",
            )
        )
        with patch(
            "app.core.mail.smtp_transport.smtplib.SMTP_SSL",
            side_effect=failing_factory,
        ):
            with pytest.raises(SMTPTransportError, match="connection reset"):
                transport.send("ana@test.com", "s", "b")

    def test_emits_email_message_with_required_headers(self) -> None:
        """The envelope is a real ``email.message.EmailMessage`` so the
        From / To / Subject headers survive SMTP transport."""
        fake = _FakeSMTP()
        transport = SMTPMailTransport(
            _settings(
                smtp_host="smtp.resend.com",
                smtp_port=465,
                smtp_user="resend",
                smtp_password="secret",
                smtp_from="onboarding@resend.dev",
            )
        )
        with patch(
            "app.core.mail.smtp_transport.smtplib.SMTP_SSL",
            side_effect=_patched_smtp_factory(fake),
        ):
            transport.send("ana@test.com", "Tu enlace APAP", "Clicka aquí.")
        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg["From"] == "onboarding@resend.dev"
        assert msg["To"] == "ana@test.com"
        assert msg["Subject"] == "Tu enlace APAP"
        body = msg.get_content()
        assert "Clicka aquí." in body
